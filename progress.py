"""
ECI Electoral Roll Downloader — Progress tracking & status.json management

Rules
-----
- Each AC has its own status.json inside its output directory.
- Each AC has its own failed.json for failed parts.
- status.json = sorted JSON array of completed part numbers.
- Load by constructing the exact path — NEVER use recursive glob.
- Save atomically (write .tmp then rename).
- Thread-safe via one threading.Lock per AC directory.
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("eroll")

# Per-directory locks keyed by str(ac_dir)
_dir_locks: dict[str, threading.Lock] = {}
_meta_lock = threading.Lock()


def _get_lock(ac_dir: Path) -> threading.Lock:
    key = str(ac_dir)
    with _meta_lock:
        if key not in _dir_locks:
            _dir_locks[key] = threading.Lock()
        return _dir_locks[key]


def _atomic_write_json(filepath: Path, data) -> None:
    """Write JSON atomically with Windows retry for PermissionError."""
    tmp = filepath.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    for attempt in range(5):
        try:
            os.replace(str(tmp), str(filepath))
            return
        except PermissionError:
            if attempt < 4:
                import time
                time.sleep(0.1 * (attempt + 1))
            else:
                log.warning("os.replace failed after retries, writing directly to %s", filepath)
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)


# ── Load / Save ─────────────────────────────────────────────────────────

def load_ac_progress(ac_dir: Path) -> set[int]:
    """Read status.json from *ac_dir* and return a set of completed parts."""
    status_file = ac_dir / "status.json"
    if not status_file.exists():
        return set()
    try:
        with open(status_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(data)
        log.warning("Unexpected status.json format in %s -- ignoring", ac_dir)
        return set()
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to read %s: %s", status_file, exc)
        return set()


async def save_ac_progress(ac_dir: Path, completed: set[int]) -> None:
    """Atomically write status.json into *ac_dir*."""
    lock = _get_lock(ac_dir)
    with lock:
        ac_dir.mkdir(parents=True, exist_ok=True)
        status_file = ac_dir / "status.json"
        _atomic_write_json(status_file, sorted(completed))


def get_pending_parts(all_parts: list[int], completed: set[int]) -> list[int]:
    """Return parts from *all_parts* that are not yet in *completed*."""
    return [p for p in all_parts if p not in completed]


# ── Per-AC failed.json ──────────────────────────────────────────────────

_failed_locks: dict[str, threading.Lock] = {}
_failed_meta_lock = threading.Lock()


def _get_failed_lock(ac_dir: Path) -> threading.Lock:
    key = str(ac_dir)
    with _failed_meta_lock:
        if key not in _failed_locks:
            _failed_locks[key] = threading.Lock()
        return _failed_locks[key]


async def record_failed_part(
    ac_dir: Path,
    ac_no: int,
    part_no: int,
    reason: str,
) -> None:
    """Append a failure entry to failed.json inside the AC directory."""
    lock = _get_failed_lock(ac_dir)
    with lock:
        ac_dir.mkdir(parents=True, exist_ok=True)
        fp_path = ac_dir / "failed.json"

        data: list = []
        if fp_path.exists():
            try:
                with open(fp_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, list):
                    data = []
            except (json.JSONDecodeError, OSError):
                data = []

        # Avoid duplicates
        if any(e.get("part") == part_no for e in data):
            return

        data.append({
            "ac": ac_no,
            "part": part_no,
            "reason": reason,
            "time": datetime.now(timezone.utc).isoformat(),
        })

        _atomic_write_json(fp_path, data)


async def clear_failed_part(ac_dir: Path, part_no: int) -> None:
    """Remove a part from failed.json after successful retry."""
    lock = _get_failed_lock(ac_dir)
    with lock:
        fp_path = ac_dir / "failed.json"
        if not fp_path.exists():
            return
        try:
            with open(fp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return
        except (json.JSONDecodeError, OSError):
            return

        updated = [e for e in data if e.get("part") != part_no]
        if len(updated) == len(data):
            return  # part wasn't in failed.json

        if updated:
            _atomic_write_json(fp_path, updated)
        else:
            fp_path.unlink(missing_ok=True)


def load_ac_failures(ac_dir: Path) -> list[dict]:
    """Read failed.json from *ac_dir*."""
    fp_path = ac_dir / "failed.json"
    if not fp_path.exists():
        return []
    try:
        with open(fp_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def count_failed_parts_in_dir(base_dir: Path) -> int:
    """Count total failed parts across all AC failed.json files under base_dir."""
    total = 0
    if not base_dir.exists():
        return 0
    # Walk district/AC dirs — NOT recursive glob on status.json
    for district_dir in base_dir.iterdir():
        if not district_dir.is_dir():
            continue
        for ac_dir in district_dir.iterdir():
            if not ac_dir.is_dir():
                continue
            fp = ac_dir / "failed.json"
            if fp.exists():
                try:
                    with open(fp, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        total += len(data)
                except (json.JSONDecodeError, OSError):
                    pass
    return total
