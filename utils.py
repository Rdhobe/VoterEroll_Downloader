"""
ECI Electoral Roll Downloader — Utility helpers
"""

import json
import logging
import re
from pathlib import Path

from config import STATE_NAMES

log = logging.getLogger("eroll")

# ── District names cache (loaded once from district_names.json) ──
_DISTRICT_NAMES: dict | None = None
_DISTRICT_FILE = Path(__file__).parent / "district_names.json"


def _load_district_names() -> dict:
    """Load district_names.json into memory (cached)."""
    global _DISTRICT_NAMES
    if _DISTRICT_NAMES is None:
        if _DISTRICT_FILE.exists():
            try:
                with open(_DISTRICT_FILE, "r", encoding="utf-8") as f:
                    _DISTRICT_NAMES = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Failed to load district_names.json: %s", exc)
                _DISTRICT_NAMES = {}
        else:
            _DISTRICT_NAMES = {}
    return _DISTRICT_NAMES


def resolve_district_name(state_cd: str, district_cd: str) -> str:
    """Look up district name from district_names.json, falling back to code."""
    names = _load_district_names()
    state_map = names.get(state_cd, {})
    name = state_map.get(district_cd, "")
    # Skip if name is same as code (placeholder)
    if name and name != district_cd:
        return name
    return ""


def safe_name(name: str) -> str:
    """Sanitise a name for use as a directory / file component."""
    name = name.strip()
    name = name.replace(" ", "_")
    name = name.replace("/", "-").replace("\\", "-")
    name = re.sub(r"[^A-Za-z0-9_\-.]", "", name)
    return name


def build_filename(
    year: int,
    pdf_gen_type: str,
    state_cd: str,
    ac_no: int,
    roll_type_ref_id: str,
    revision_no: int,
    lang_cd: str,
    part_no: int,
) -> str:
    """
    Build the canonical PDF filename.

    Example: 2026-EROLLGEN-S22-101-SIR-FinalRoll-Revision1-ENG-44-WI.pdf
    """
    return (
        f"{year}-{pdf_gen_type}-{state_cd}-{ac_no}-"
        f"{roll_type_ref_id}-Revision{revision_no}-"
        f"{lang_cd}-{part_no}-WI.pdf"
    )


def build_ac_dir(
    output_base: str,
    state_cd: str,
    district_name: str,
    ac_no: int,
    ac_name: str,
) -> Path:
    """
    Build the output directory path for an Assembly Constituency.

    Structure: output_base / State_Name / District_Name / AC_{no}_{name}
    Example:   output_finalroll / West_Bengal / ALIPURDUAR / AC_1_Alipurduar
    """
    state_name = STATE_NAMES.get(state_cd, state_cd)
    return (
        Path(output_base)
        / safe_name(state_name)
        / safe_name(district_name)
        / f"AC_{ac_no}_{safe_name(ac_name)}"
    )


def validate_pdf(data: bytes) -> bool:
    """Return True if *data* looks like a valid PDF (starts with %PDF)."""
    if not data or len(data) < 8:
        return False
    return data[:5] == b"%PDF-"


def get_district_name(district_cd: str, ac_list: list[dict]) -> str:
    """
    Derive a human-readable district name from the AC list.

    Falls back to the raw district code if no AC carries a districtName field.
    """
    for ac in ac_list:
        if ac.get("districtCd") == district_cd:
            return ac.get("districtName", "") or district_cd
    return district_cd


def get_districts_from_ac_list(
    ac_list: list[dict], state_cd: str = ""
) -> dict[str, str]:
    """
    Build a mapping of district_cd -> district_name from the AC list.

    Resolution order:
    1. district_names.json (most reliable — manually curated)
    2. API districtName field (if available)
    3. Single-AC districts: use the AC name
    4. Fallback: district code

    Returns e.g. {"S2501": "Cooch Behar", "S2523": "Kalimpong", ...}
    """
    from collections import defaultdict

    # Detect state_cd from AC data if not provided
    if not state_cd and ac_list:
        state_cd = ac_list[0].get("stateCd", "")

    districts: dict[str, str] = {}
    acs_by_dist: dict[str, list[str]] = defaultdict(list)

    for ac in ac_list:
        dcd = ac.get("districtCd", "")
        if not dcd:
            continue
        if dcd not in districts:
            districts[dcd] = ""
        acs_by_dist[dcd].append(ac.get("asmblyName", ""))

    # Resolve names with priority: district_names.json > API > inference > code
    for dcd in districts:
        # 1. Try district_names.json
        json_name = resolve_district_name(state_cd, dcd)
        if json_name:
            districts[dcd] = json_name
            continue

        # 2. Try API districtName field
        for ac in ac_list:
            if ac.get("districtCd") == dcd:
                api_name = ac.get("districtName", "")
                if api_name and api_name != dcd:
                    districts[dcd] = api_name
                    break

        if districts[dcd]:
            continue

        # 3. Single-AC districts: use AC name
        ac_names = acs_by_dist.get(dcd, [])
        if len(ac_names) == 1 and ac_names[0]:
            districts[dcd] = ac_names[0]
        else:
            # 4. Fallback to code
            districts[dcd] = dcd

    return dict(sorted(districts.items(), key=lambda x: x[1]))
