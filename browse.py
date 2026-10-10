"""
ECI Electoral Roll Downloader — Web File Browser + Download API

Usage:
    python browse.py [--port 5000] [--output output_finalroll]

Browse downloaded electoral roll PDFs and trigger new downloads via web UI.
"""

# ── Known ECI roll type slugs per state (for fallback when API is blocked) ──
# These are the actual rollTypeRefId values used by ECI for pre-generated PDFs.
# Format: state_cd -> [(rollTypeRefId, rollType, pdfGenType, revisionNo, displayName)]
_STATE_ROLL_SLUGS: dict = {
    # States with pre-generated 2026 PDFs on CDN (Strategy 0 in downloader)
    "S25": "sir-finalroll-2026",   # West Bengal
    "S22": "sir-finalroll-2026",   # Tamil Nadu
    "S26": "sir-finalroll-2026",   # Chhattisgarh
    "S20": "sir-finalroll-2026",   # Rajasthan
    "S11": "sir-finalroll-2026",   # Kerala
    "S12": "sir-finalroll-2026",   # Madhya Pradesh
    "S06": "sir-finalroll-2026",   # Gujarat
    "S03": "sir-finalroll-2026",   # Assam
    # Default for all other states
    "DEFAULT": "sir-finalroll-2026",
}

import argparse
import asyncio
import io
import logging
import os
import re
import threading
import time
import uuid
import zipfile
from pathlib import Path

import requests as http_requests
from flask import (
    Flask,
    jsonify,
    request,
    send_file,
    send_from_directory,
    abort,
)
from flask_cors import CORS

import json as json_module

from config import (
    DEFAULT_YEAR,
    GATEWAY_API,
    HEADERS as ECI_HEADERS,
    LANG_MAP,
    STATE_NAMES,
)

log = logging.getLogger("eroll.browse")

app = Flask(__name__, static_folder="frontend", static_url_path="")
CORS(app)  # Enable CORS for frontend requests

# Configured at startup
OUTPUT_DIR: Path = Path("output_finalroll")

# Internal metadata files to hide from browsing
_HIDDEN = {"status.json", "status.json.tmp", "failed.json", "failed_parts.json", "download.log"}

# ── District names mapping ────────────────────────────────────────────────
_DISTRICT_NAMES: dict = {}
_DISTRICT_FILE = Path(__file__).parent / "district_names.json"


def _load_district_names() -> dict:
    """Load district_names.json into memory."""
    global _DISTRICT_NAMES
    if not _DISTRICT_NAMES and _DISTRICT_FILE.exists():
        try:
            with open(_DISTRICT_FILE, "r", encoding="utf-8") as f:
                _DISTRICT_NAMES = json_module.load(f)
        except (json_module.JSONDecodeError, OSError) as exc:
            log.warning("Failed to load district_names.json: %s", exc)
    return _DISTRICT_NAMES


def _get_district_name(state_cd: str, district_cd: str) -> str:
    """Look up district name from the mapping, falling back to code."""
    names = _load_district_names()
    state_map = names.get(state_cd, {})
    return state_map.get(district_cd, district_cd)


def _resolve_state_code(state_input: str) -> str | None:
    """Resolve a state name or code to its code. Returns None if not found."""
    if not state_input:
        return None
    # Direct code match
    upper = state_input.upper()
    if upper in STATE_NAMES:
        return upper
    # Name match (case-insensitive, substring)
    lower = state_input.lower()
    for code, name in STATE_NAMES.items():
        if lower == name.lower() or lower in name.lower():
            return code
    return None

# Regex to parse canonical PDF filename
_PDF_RE = re.compile(
    r"^(\d{4})-(\w+)-([A-Z]\d+)-(\d+)-(.+)-Revision(\d+)-([A-Z]{3})-(\d+)-WI\.pdf$",
    re.IGNORECASE,
)


# ── Helpers ──────────────────────────────────────────────────────────────

def safe_resolve(rel_path: str) -> Path:
    """Resolve a user-supplied path, ensuring it stays inside OUTPUT_DIR."""
    rel_path = rel_path.replace("\\", "/").strip("/")
    target = (OUTPUT_DIR / rel_path).resolve()
    base = OUTPUT_DIR.resolve()
    if not str(target).startswith(str(base)):
        abort(403, "Path traversal not allowed")
    return target


def human_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}" if unit != "B" else f"{size_bytes} B"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def parse_pdf_filename(filename: str) -> dict | None:
    """Extract metadata from a canonical PDF filename."""
    m = _PDF_RE.match(filename)
    if not m:
        return None
    year, gen_type, state_cd, ac_no, roll_ref, rev, lang_cd, part_no = m.groups()
    return {
        "year": int(year),
        "state_cd": state_cd,
        "state_name": STATE_NAMES.get(state_cd, state_cd),
        "ac_no": int(ac_no),
        "roll_type": roll_ref,
        "revision": int(rev),
        "lang_cd": lang_cd,
        "lang_name": LANG_MAP.get(lang_cd, lang_cd),
        "part_no": int(part_no),
    }


def build_breadcrumbs(rel_path: str) -> list[dict]:
    """Build breadcrumb entries from a relative path."""
    crumbs = [{"name": "All States", "path": ""}]
    if not rel_path:
        return crumbs
    parts = rel_path.split("/")
    for i, part in enumerate(parts):
        path = "/".join(parts[: i + 1])
        name = part
        # Enrich state code with human name
        if i == 0 and part in STATE_NAMES:
            name = f"{STATE_NAMES[part]} ({part})"
        # Clean up AC directory names: AC_62_Villivakkam -> 62 - Villivakkam
        if part.startswith("AC_"):
            ac_match = re.match(r"AC_(\d+)_(.*)", part)
            if ac_match:
                name = f"AC {ac_match.group(1)} - {ac_match.group(2).replace('_', ' ')}"
        crumbs.append({"name": name, "path": path})
    return crumbs


def scan_directory(rel_path: str) -> dict:
    """Scan a directory and return structured contents."""
    target = safe_resolve(rel_path)
    if not target.is_dir():
        abort(404, "Directory not found")

    dirs = []
    files = []

    for entry in sorted(target.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
        if entry.name in _HIDDEN or entry.name.startswith("."):
            continue

        if entry.is_dir():
            # Count only immediate children (fast — no recursive scan)
            try:
                children = list(entry.iterdir())
                pdf_count = sum(1 for f in children if f.is_file() and f.suffix.lower() == ".pdf")
                sub_dirs = sum(1 for f in children if f.is_dir())
            except PermissionError:
                pdf_count = 0
                sub_dirs = 0
            rel = str(entry.relative_to(OUTPUT_DIR)).replace("\\", "/")
            display_name = entry.name
            # Enrich state code dirs
            if entry.name in STATE_NAMES:
                display_name = f"{STATE_NAMES[entry.name]} ({entry.name})"
            # Enrich AC dirs
            ac_match = re.match(r"AC_(\d+)_(.*)", entry.name)
            if ac_match:
                display_name = f"AC {ac_match.group(1)} - {ac_match.group(2).replace('_', ' ')}"

            dirs.append({
                "name": entry.name,
                "display_name": display_name,
                "path": rel,
                "pdf_count": pdf_count,
                "sub_dirs": sub_dirs,
            })

        elif entry.is_file() and entry.suffix.lower() == ".pdf":
            rel = str(entry.relative_to(OUTPUT_DIR)).replace("\\", "/")
            meta = parse_pdf_filename(entry.name)
            files.append({
                "name": entry.name,
                "path": rel,
                "size": entry.stat().st_size,
                "size_human": human_size(entry.stat().st_size),
                "meta": meta,
            })

    return {
        "path": rel_path,
        "breadcrumbs": build_breadcrumbs(rel_path),
        "dirs": dirs,
        "files": files,
        "total_dirs": len(dirs),
        "total_files": len(files),
    }


# ── API Routes ───────────────────────────────────────────────────────────

@app.route("/api/browse")
def api_browse():
    """Return directory listing as JSON."""
    rel_path = request.args.get("path", "").strip("/")
    return jsonify(scan_directory(rel_path))


@app.route("/api/search")
def api_search():
    """Search for PDFs by name."""
    query = request.args.get("q", "").strip().lower()
    scope = request.args.get("path", "").strip("/")
    if not query or len(query) < 2:
        return jsonify({"results": [], "truncated": False})

    target = safe_resolve(scope)
    results = []
    for pdf_path in target.rglob("*.pdf"):
        if query in str(pdf_path.relative_to(OUTPUT_DIR)).lower():
            rel = str(pdf_path.relative_to(OUTPUT_DIR)).replace("\\", "/")
            meta = parse_pdf_filename(pdf_path.name)
            stat = pdf_path.stat()
            results.append({
                "name": pdf_path.name,
                "path": rel,
                "dir": str(pdf_path.parent.relative_to(OUTPUT_DIR)).replace("\\", "/"),
                "size": stat.st_size,
                "size_human": human_size(stat.st_size),
                "meta": meta,
            })
            if len(results) >= 200:
                break

    return jsonify({"results": results, "truncated": len(results) >= 200})


@app.route("/api/download")
def api_download():
    """Download a single file."""
    file_path = request.args.get("file", "").strip("/")
    if not file_path:
        abort(400, "Missing 'file' parameter")
    target = safe_resolve(file_path)
    if not target.is_file():
        abort(404, "File not found")
    return send_file(target, as_attachment=True, download_name=target.name)


@app.route("/api/view")
def api_view():
    """View a single PDF inline in the browser (no download prompt)."""
    file_path = request.args.get("file", "").strip("/")
    if not file_path:
        abort(400, "Missing 'file' parameter")
    target = safe_resolve(file_path)
    if not target.is_file():
        abort(404, "File not found")
    return send_file(target, as_attachment=False, download_name=target.name)


@app.route("/api/download-zip", methods=["POST"])
def api_download_zip():
    """Download multiple files/folders as a ZIP."""
    data = request.get_json()
    files = data.get("files", [])
    folders = data.get("folders", [])

    # Expand folders to individual PDF files
    all_files = list(files)
    for folder_path in folders:
        target = safe_resolve(folder_path)
        if target.is_dir():
            for pdf in target.rglob("*.pdf"):
                rel = str(pdf.relative_to(OUTPUT_DIR)).replace("\\", "/")
                all_files.append(rel)

    # Deduplicate preserving order
    seen = set()
    unique_files = []
    for f in all_files:
        if f not in seen:
            seen.add(f)
            unique_files.append(f)

    if not unique_files:
        abort(400, "No files to download")
    if len(unique_files) > 10000:
        abort(400, f"Too many files ({len(unique_files)}). Narrow your selection.")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path in unique_files:
            target = safe_resolve(rel_path)
            if target.is_file():
                zf.write(target, rel_path.replace("\\", "/"))
    buf.seek(0)

    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="eroll_selected.zip",
    )


_stats_cache = None
_stats_cache_time = 0


@app.route("/api/stats")
def api_stats():
    """Return overall statistics (cached for 30s)."""
    global _stats_cache, _stats_cache_time
    now = time.time()
    if _stats_cache and (now - _stats_cache_time) < 30:
        return jsonify(_stats_cache)

    total_pdfs = 0
    total_size = 0
    # Single pass with os.walk (much faster than two rglob calls)
    for root, _dirs, files in os.walk(OUTPUT_DIR):
        for f in files:
            if f.lower().endswith(".pdf"):
                total_pdfs += 1
                try:
                    total_size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass

    # Build reverse lookup: state_name_safe -> (code, display_name)
    name_to_code = {}
    for code, name in STATE_NAMES.items():
        from utils import safe_name
        name_to_code[safe_name(name)] = code

    states = []
    for d in OUTPUT_DIR.iterdir():
        if not d.is_dir():
            continue
        # Match by code or by safe_name(state_name)
        if d.name in STATE_NAMES:
            states.append({"code": d.name, "name": STATE_NAMES[d.name], "dir": d.name})
        elif d.name in name_to_code:
            code = name_to_code[d.name]
            states.append({"code": code, "name": STATE_NAMES[code], "dir": d.name})

    _stats_cache = {
        "total_pdfs": total_pdfs,
        "total_size": total_size,
        "total_size_human": human_size(total_size),
        "states": states,
    }
    _stats_cache_time = now
    return jsonify(_stats_cache)


# ── ECI Proxy Helpers ────────────────────────────────────────────────────

def _eci_get(path: str, params: dict | None = None) -> dict | list:
    """Synchronous GET to the ECI gateway API."""
    url = f"{GATEWAY_API}/{path}"
    resp = http_requests.get(url, headers=ECI_HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _eci_post(path: str, body: dict) -> dict:
    """Synchronous POST to the ECI gateway API."""
    url = f"{GATEWAY_API}/{path}"
    resp = http_requests.post(url, headers=ECI_HEADERS, json=body, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ── ECI Proxy API Routes ────────────────────────────────────────────────

@app.route("/api/eci/states")
def api_eci_states():
    """Return the static list of states."""
    states = [
        {"code": code, "name": name}
        for code, name in sorted(STATE_NAMES.items(), key=lambda x: x[1])
    ]
    return jsonify({"states": states, "default_year": DEFAULT_YEAR})


@app.route("/api/eci/roll-types")
def api_eci_roll_types():
    """Proxy: fetch published roll types for a state+year.

    Accepts state code (S25) or name (West Bengal).
    Tries aiohttp (same as CLI), then requests, then returns a smart fallback
    roll type so the UI remains fully usable even when ECI blocks server calls.
    """
    state_input = request.args.get("state", "")
    year_str = request.args.get("year", str(DEFAULT_YEAR))
    state = _resolve_state_code(state_input)
    if not state:
        abort(400, f"Unknown state: '{state_input}'")

    try:
        year_int = int(year_str)
    except ValueError:
        year_int = DEFAULT_YEAR

    # ── Attempt 1: aiohttp (same library as the CLI downloader) ──────────
    try:
        import asyncio as _asyncio
        import aiohttp as _aiohttp
        from api import get_roll_types as _get_roll_types

        async def _fetch_rolls():
            async with _aiohttp.ClientSession() as _session:
                return await _get_roll_types(_session, state, year_int)

        rolls = _asyncio.run(_fetch_rolls())
        if rolls:
            log.info("roll-types via aiohttp: %d types for %s/%s", len(rolls), state, year_int)
            return jsonify({"roll_types": rolls})
    except Exception as exc:
        log.warning("aiohttp roll-types failed for %s/%s: %s", state, year_int, exc)

    # ── Attempt 2: requests (synchronous) ────────────────────────────────
    try:
        from api import encrypt_payloads
        accept_yek, accept_rotcev, param_state, param_year, param_mis_key = encrypt_payloads(state, year_int)
        
        headers = ECI_HEADERS.copy()
        headers["accept_yek"] = accept_yek
        headers["accept_rotcev"] = accept_rotcev
        
        params = {
            "stateCd": param_state,
            "year": param_year,
            "misKey": param_mis_key
        }
        
        url = f"{GATEWAY_API}/printing-publish/get-publish-eroll-type"
        resp = http_requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        payload = data.get("payload", [])
        if not isinstance(payload, list):
            payload = []
        published = [r for r in payload if r.get("publish") == "Y"]
        if published:
            log.info("roll-types via requests: %d types", len(published))
            return jsonify({"roll_types": published})
    except Exception as exc:
        log.warning("requests roll-types failed: %s", exc)


    # ── Attempt 3: Smart fallback using known ECI CDN slug pattern ────────
    # ECI pre-generates PDFs at: voters.eci.gov.in/eroll/{year}/{state}/{slug}/{ac}/...
    # The slug is typically "sir-finalroll-{year}" for most states.
    # This enables the full UI flow (languages via LANG_MAP, parts from API).
    slug = _STATE_ROLL_SLUGS.get(state, _STATE_ROLL_SLUGS["DEFAULT"])
    # Update year in slug
    import re as _re
    slug = _re.sub(r'\d{4}', str(year_int), slug)

    fallback_roll = {
        "rollType": "FINALROLL",
        "rollTypeRefId": slug,
        "pdfGenType": "PART",
        "revisionNo": 1,
        "displayName": f"Final Electoral Roll {year_int}",
        "publish": "Y",
        "publishDate": f"{year_int}-01-01",
        "_fallback": True,
    }
    log.info(
        "roll-types fallback for %s/%s: using slug '%s'",
        state, year_int, slug,
    )
    return jsonify({"roll_types": [fallback_roll], "fallback": True})


@app.route("/api/eci/districts")
def api_eci_districts():
    """Return districts for a state, with names from district_names.json.

    GET /api/eci/districts?state=S25
    GET /api/eci/districts?state=West Bengal

    Returns: {districts: [{code, name, ac_count, acs: [{no, name}]}]}
    """
    state_input = request.args.get("state", "")
    state = _resolve_state_code(state_input)
    if not state:
        abort(400, f"Unknown state: '{state_input}'")
    try:
        data = _eci_get("common/constituencies", {"stateCode": state})
        if not isinstance(data, list):
            data = []
    except Exception as exc:
        log.warning("districts proxy error: %s", exc)
        return jsonify({"districts": [], "error": str(exc)}), 502

    from collections import defaultdict

    groups: dict[str, list] = defaultdict(list)
    for ac in data:
        dcd = ac.get("districtCd", "")
        if dcd:
            groups[dcd].append({
                "no": ac["asmblyNo"],
                "name": ac.get("asmblyName", ""),
            })

    districts = []
    for dcd in sorted(groups.keys()):
        acs = sorted(groups[dcd], key=lambda a: a["no"])
        districts.append({
            "code": dcd,
            "name": _get_district_name(state, dcd),
            "ac_count": len(acs),
            "acs": acs,
        })

    return jsonify({
        "state_code": state,
        "state_name": STATE_NAMES.get(state, state),
        "districts": districts,
    })


@app.route("/api/eci/constituencies")
def api_eci_constituencies():
    """Proxy: fetch ACs for a state, optionally filtered by district.

    Accepts state code (S25) or name (West Bengal).
    Optional: district code (S2501) or name (Cooch Behar).
    """
    state_input = request.args.get("state", "")
    district_input = request.args.get("district", "")
    state = _resolve_state_code(state_input)
    if not state:
        abort(400, f"Unknown state: '{state_input}'")
    try:
        data = _eci_get("common/constituencies", {"stateCode": state})
        if not isinstance(data, list):
            data = []

        # Enrich with district names
        for ac in data:
            dcd = ac.get("districtCd", "")
            ac["districtName"] = _get_district_name(state, dcd)

        # Filter by district if provided
        if district_input:
            dl = district_input.lower()
            data = [
                ac for ac in data
                if dl in ac.get("districtCd", "").lower()
                or dl in ac.get("districtName", "").lower()
            ]

        return jsonify({"constituencies": data})
    except Exception as exc:
        log.warning("constituencies proxy error: %s", exc)
        return jsonify({"constituencies": [], "error": str(exc)}), 502


@app.route("/api/eci/languages", methods=["POST"])
def api_eci_languages():
    """Proxy: fetch available languages for an AC.

    If rollTypeRefId is a fallback slug (containing 'sir-'), or the ECI API fails,
    returns all known languages from LANG_MAP so the UI can proceed.
    """
    body = request.get_json()
    if not body:
        abort(400, "Missing JSON body")

    roll_ref_id = body.get("rollTypeRefId", "")

    # If using fallback roll type, skip the ECI API and return all known languages
    is_fallback_ref = (
        roll_ref_id.startswith("sir-") or
        roll_ref_id == "AUTO" or
        body.get("_fallback")
    )

    if not is_fallback_ref:
        # Try the live ECI API first
        try:
            data = _eci_post("printing-publish/get-ac-languages", {
                "stateCd": body["stateCd"],
                "acNumber": body["acNumber"],
                "rollTypeRefId": roll_ref_id,
                "pdfGenType": body.get("pdfGenType", "PART"),
            })
            payload = data.get("payload", {})
            if isinstance(payload, dict) and payload:
                log.info("languages from ECI API for AC %s: %s",
                         body.get("acNumber"), list(payload.keys()))
                return jsonify({"languages": payload})
        except Exception as exc:
            log.warning("languages proxy error for AC %s: %s",
                        body.get("acNumber"), exc)

    # Fallback: return all known languages from config (always works)
    log.info("languages fallback for AC %s: returning all %d languages",
             body.get("acNumber"), len(LANG_MAP))
    return jsonify({"languages": LANG_MAP, "fallback": True})


@app.route("/api/eci/parts", methods=["POST"])
def api_eci_parts():
    """Proxy: fetch part list for an AC.

    If rollTypeRefId is a fallback slug (sir-*), tries to fetch parts anyway,
    then falls back to returning all_parts=True so the downloader handles it.
    """
    body = request.get_json()
    if not body:
        abort(400, "Missing JSON body")

    roll_ref_id = body.get("rollTypeRefId", "")
    is_fallback_ref = (
        roll_ref_id.startswith("sir-") or
        roll_ref_id == "AUTO" or
        body.get("_fallback")
    )

    if not is_fallback_ref:
        # Try live ECI API
        try:
            data = _eci_post("printing-publish/get-publish-part-list", {
                "stateCd": body["stateCd"],
                "acNumber": body["acNumber"],
                "year": body["year"],
                "rollType": body["rollType"],
                "rollTypeRefId": roll_ref_id,
                "pdfGenType": body.get("pdfGenType", "PART"),
                "revisionNo": body.get("revisionNo", 1),
            })
            payload = data.get("payload", [])
            if isinstance(payload, list) and payload:
                parts = sorted(p["partNumber"] for p in payload if "partNumber" in p)
                if parts:
                    return jsonify({"parts": parts})
        except Exception as exc:
            log.warning("parts proxy error for AC %s: %s",
                        body.get("acNumber"), exc)

    # Fallback: probe the ECI CDN directly to discover real part numbers.
    # This lets the UI show actual checkboxes instead of "All Parts Mode".
    state_cd = body.get("stateCd", "")
    ac_number = body.get("acNumber")
    year = body.get("year", DEFAULT_YEAR)
    lang_cd = body.get("langCd") or body.get("lang", "ENG")
    pdf_gen_type = body.get("pdfGenType", "PART")
    revision_no = body.get("revisionNo", 1)

    if state_cd and ac_number and roll_ref_id:
        try:
            import asyncio as _asyncio
            import aiohttp as _aiohttp
            from config import EROLL_DIRECT_URL as _DIRECT_URL, HEADERS as _H
            from utils import build_filename as _bf

            async def _probe_cdn():
                found = []
                roll_slug = roll_ref_id.lower()
                state_lower = state_cd.lower()
                dl_headers = {"User-Agent": _H["User-Agent"], "Referer": _H["Referer"], "Accept": "*/*"}
                max_consecutive_misses = 5
                consecutive_misses = 0
                part_no = 1
                sem = _asyncio.Semaphore(20)

                async def _check(session, p):
                    fn = _bf(
                        year=year, pdf_gen_type=pdf_gen_type, state_cd=state_cd,
                        ac_no=ac_number, roll_type_ref_id=roll_ref_id,
                        revision_no=revision_no, lang_cd=lang_cd, part_no=p,
                    )
                    url = f"{_DIRECT_URL}/{year}/{state_lower}/{roll_slug}/{ac_number}/{fn}"
                    async with sem:
                        try:
                            async with session.head(url, headers=dl_headers,
                                                    timeout=_aiohttp.ClientTimeout(total=10),
                                                    allow_redirects=True) as resp:
                                return p, resp.status == 200
                        except Exception:
                            return p, False

                connector = _aiohttp.TCPConnector(ssl=False)
                async with _aiohttp.ClientSession(connector=connector) as session:
                    while part_no <= 1000:
                        batch = list(range(part_no, min(part_no + 19, 501)))
                        results = await _asyncio.gather(*[_check(session, p) for p in batch])
                        batch_found = [p for p, ok in results if ok]
                        found.extend(batch_found)
                        if batch_found:
                            consecutive_misses = 0
                        else:
                            consecutive_misses += len(batch)
                        if consecutive_misses >= max_consecutive_misses:
                            break
                        part_no = batch[-1] + 1
                return sorted(found)

            probed_parts = _asyncio.run(_probe_cdn())
            if probed_parts:
                log.info("parts CDN probe for AC %s: found %d parts", ac_number, len(probed_parts))
                return jsonify({"parts": probed_parts, "probed": True})
        except Exception as exc:
            log.warning("parts CDN probe failed for AC %s: %s", ac_number, exc)

    # Last resort: signal the frontend to download all parts (downloader handles it)
    log.info("parts fallback for AC %s: returning all_parts=True", body.get("acNumber"))
    return jsonify({"parts": [], "all_parts": True, "fallback": True})



# ── Background Download Task Management ─────────────────────────────────

_download_tasks: dict[str, dict] = {}


def _run_download_in_thread(task_id: str, cfg: dict):
    """Run the async downloader in a new thread with its own event loop."""
    from downloader import run as downloader_run

    def on_progress(info: dict):
        """Callback from downloader — update task progress snapshot."""
        _download_tasks[task_id]["progress"] = info

    cfg["progress_callback"] = on_progress

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        _download_tasks[task_id]["status"] = "running"
        result = loop.run_until_complete(downloader_run(cfg))
        _download_tasks[task_id]["status"] = "completed"
        _download_tasks[task_id]["result"] = result
    except Exception as exc:
        _download_tasks[task_id]["status"] = "failed"
        _download_tasks[task_id]["error"] = str(exc)
        log.exception("Download task %s failed", task_id)
    finally:
        loop.close()


@app.route("/api/eci/download", methods=["POST"])
def api_eci_download():
    """Start a background download task.

    Accepts state/district by code or name:
      {"state": "West Bengal", "district": "Cooch Behar", "lang": "ENG"}
    or:
      {"stateCd": "S25", "districtName": "Cooch Behar", "langCd": "ENG"}
    """
    body = request.get_json()
    if not body:
        abort(400, "Missing JSON body")

    # Resolve state: accept "state" (name) or "stateCd" (code)
    state_input = body.get("state") or body.get("stateCd", "")
    state_cd = _resolve_state_code(state_input)
    if not state_cd:
        abort(400, f"Unknown state: '{state_input}'")

    # Resolve district filter: prefer code (always matches), fall back to name
    district_input = (
        body.get("districtCd")
        or body.get("district")
        or body.get("districtName", "")
    )
    district_filters = [district_input] if district_input else []

    force = body.get("force", False)

    # Accept a pre-resolved roll type from the UI to bypass the blocked live ECI API.
    # The frontend sends the rollTypeInfo object from its own /api/eci/roll-types call
    # (which already has fallback logic).  If omitted, the downloader will try the live API
    # and fall back on its own.
    roll_type_info = body.get("rollTypeInfo")  # optional dict

    task_id = str(uuid.uuid4())[:8]
    cfg = {
        "state": state_cd,
        "lang": body.get("lang") or body.get("langCd", "ENG"),
        "year": body.get("year", DEFAULT_YEAR),
        "output": str(OUTPUT_DIR),
        "concurrency": 10,
        "resume": not force,
        "force": bool(force),
        "dry_run": False,
        "ac_filter": body.get("acNumber") or body.get("ac"),
        "district_filters": district_filters,
        "start_part": body.get("startPart"),
        "end_part": body.get("endPart"),
        "roll_type_info": roll_type_info,  # pre-resolved; None = downloader fetches live
    }

    _download_tasks[task_id] = {
        "status": "starting",
        "cfg": cfg,
        "started_at": time.time(),
        "result": None,
        "error": None,
        "progress": None,
    }

    thread = threading.Thread(
        target=_run_download_in_thread,
        args=(task_id, cfg),
        daemon=True,
    )
    thread.start()

    return jsonify({"task_id": task_id, "status": "starting"})


@app.route("/api/eci/download-status")
def api_eci_download_status():
    """Check the status of a download task."""
    task_id = request.args.get("task_id", "")
    if not task_id or task_id not in _download_tasks:
        abort(404, "Task not found")
    task = _download_tasks[task_id]
    progress = task.get("progress")
    # Add human-readable bytes to progress
    if progress and progress.get("total_bytes"):
        progress["total_bytes_human"] = human_size(progress["total_bytes"])
    return jsonify({
        "task_id": task_id,
        "status": task["status"],
        "elapsed": int(time.time() - task["started_at"]),
        "result": task.get("result"),
        "error": task.get("error"),
        "progress": progress,
    })


# ── Serve React App ─────────────────────────────────────────────────────

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_react(path):
    """Serve the React app (falls through for non-API routes)."""
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Browse downloaded electoral roll PDFs")
    p.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    p.add_argument("--output", default="output_finalroll", help="Output directory")
    p.add_argument("--host", default="127.0.0.1", help="Host (default: 127.0.0.1)")
    args = p.parse_args()

    global OUTPUT_DIR
    OUTPUT_DIR = Path(args.output).resolve()
    if not OUTPUT_DIR.is_dir():
        print(f"Error: output directory '{args.output}' does not exist.")
        raise SystemExit(1)

    print()
    print("  ECI Electoral Roll — File Browser")
    print(f"  Serving: {OUTPUT_DIR}")
    print(f"  Open:    http://{args.host}:{args.port}")
    print()
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
