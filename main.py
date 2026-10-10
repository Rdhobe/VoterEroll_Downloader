#!/usr/bin/env python3
"""
ECI Electoral Roll Downloader -- CLI entry point

District-centric download flow:
  State -> Year -> Roll Type -> District(s) -> ACs -> Language

Usage:
    python main.py --state S25 --district ALIPURDUAR --lang ENG --resume
    python main.py --state S22 --district Tiruvannamalai --ac 62 --resume
    python main.py --state S25 --lang ENG --resume          # all districts
    python main.py --state S25 --list-districts
    python main.py --state S25 --list-acs
    python main.py --state S25 --district ALIPURDUAR --dry-run
"""

import argparse
import asyncio
import sys

import aiohttp

from api import get_constituencies, get_roll_types
from config import (
    DEFAULT_CONCURRENCY,
    DEFAULT_LANG,
    DEFAULT_STATE,
    DEFAULT_YEAR,
    LANG_MAP,
    STATE_NAMES,
)
from logger import setup_logger
from utils import get_districts_from_ac_list

BANNER = """
==================================================
    ECI Electoral Roll PDF Downloader
    ----------------------------------
  Bulk download voter-list PDFs from ECI gateway
  Flow: State > District > AC > Parts
==================================================
"""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Bulk-download Electoral Roll PDFs from ECI gateway (district-wise)",
    )
    p.add_argument("--state", default=DEFAULT_STATE,
                   help="State code (default: S22). Use --list-states to see all.")
    p.add_argument("--lang", default=DEFAULT_LANG, help="Language code (default: ENG)")
    p.add_argument("--year", type=int, default=DEFAULT_YEAR, help="Year (default: 2026)")
    p.add_argument("--output", default="output_finalroll", help="Output directory")
    p.add_argument("--district", nargs="+", default=None,
                   help="District name(s) to download (substring match). "
                        "Omit to download all districts.")
    p.add_argument("--ac", type=int, default=None, help="Single AC number to download")
    p.add_argument("--start-part", type=int, default=None, help="Start from part number")
    p.add_argument("--end-part", type=int, default=None, help="End at part number")
    p.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY,
                   help="Max concurrent downloads (default: 20)")
    p.add_argument("--resume", action="store_true", help="Skip already downloaded parts")
    p.add_argument("--dry-run", action="store_true", help="Show plan without downloading")
    p.add_argument("--list-states", action="store_true", help="List all state codes and exit")
    p.add_argument("--list-districts", action="store_true",
                   help="List all districts for the state and exit")
    p.add_argument("--list-acs", action="store_true", help="List all ACs (grouped by district)")
    p.add_argument("--yes", "-y", action="store_true",
                   help="Skip confirmation prompt for large downloads")
    return p.parse_args()


def list_states() -> None:
    """Print all supported state codes."""
    print("\nSupported States:\n")
    print(f"  {'Code':<6}  {'State Name'}")
    print(f"  {'----':<6}  {'----------'}")
    for code in sorted(STATE_NAMES.keys()):
        print(f"  {code:<6}  {STATE_NAMES[code]}")
    print()


async def list_districts(state_cd: str, year: int) -> None:
    """Print all districts for a state, grouped with AC count."""
    async with aiohttp.ClientSession() as session:
        acs = await get_constituencies(session, state_cd)
        rolls = await get_roll_types(session, state_cd, year)

    if not acs:
        print(f"No constituencies found for {state_cd}")
        return

    state_name = STATE_NAMES.get(state_cd, state_cd)
    districts = get_districts_from_ac_list(acs)

    print(f"\nDistricts for {state_name} ({state_cd}):\n")
    print(f"  {'#':>3}  {'District Code':<14}  {'District Name':<25}  {'ACs'}")
    print(f"  {'---':>3}  {'-'*14}  {'-'*25}  {'---'}")

    for idx, (dcd, dname) in enumerate(districts.items(), 1):
        ac_count = sum(1 for ac in acs if ac.get("districtCd") == dcd)
        print(f"  {idx:>3}  {dcd:<14}  {dname:<25}  {ac_count}")

    print(f"\nTotal: {len(districts)} districts, {len(acs)} ACs")

    if rolls:
        r = rolls[0]
        print(f"Roll type: {r['displayName']} (published {r.get('publishDate', '?')})")


async def list_acs(state_cd: str, year: int) -> None:
    """Print all ACs grouped by district."""
    async with aiohttp.ClientSession() as session:
        acs = await get_constituencies(session, state_cd)
        rolls = await get_roll_types(session, state_cd, year)

    if not acs:
        print(f"No constituencies found for {state_cd}")
        return

    state_name = STATE_NAMES.get(state_cd, state_cd)
    districts = get_districts_from_ac_list(acs)

    print(f"\nAssembly Constituencies for {state_name} ({state_cd}):\n")

    if rolls:
        r = rolls[0]
        print(f"Roll type: {r['displayName']} (published {r.get('publishDate', '?')})\n")

    for dcd, dname in districts.items():
        dist_acs = sorted(
            [a for a in acs if a.get("districtCd") == dcd],
            key=lambda a: a["asmblyNo"],
        )
        print(f"  District: {dname} ({len(dist_acs)} ACs)")
        print(f"  {'No':>6}  {'AC Name'}")
        print(f"  {'------':>6}  {'-------'}")
        for ac in dist_acs:
            print(f"  {ac['asmblyNo']:>6}  {ac.get('asmblyName', '?')}")
        print()

    print(f"Total: {len(districts)} districts, {len(acs)} ACs")


async def async_main() -> None:
    args = parse_args()

    # --list-states (no network needed)
    if args.list_states:
        list_states()
        return

    log = setup_logger(args.output)

    print(BANNER)
    state_name = STATE_NAMES.get(args.state, args.state)
    lang_name = LANG_MAP.get(args.lang, args.lang)
    print(f"  State       : {state_name} ({args.state})")
    print(f"  Language    : {lang_name} ({args.lang})")
    print(f"  Year        : {args.year}")
    print(f"  Output      : {args.output}")
    print(f"  Concurrency : {args.concurrency}")
    print(f"  Resume      : {'yes' if args.resume else 'no'}")
    if args.district:
        print(f"  District(s) : {', '.join(args.district)}")
    else:
        print(f"  District(s) : ALL")
    if args.ac:
        print(f"  AC Filter   : {args.ac}")
    print()

    # --list-districts mode
    if args.list_districts:
        await list_districts(args.state, args.year)
        return

    # --list-acs mode
    if args.list_acs:
        await list_acs(args.state, args.year)
        return

    # Build config dict for the download engine
    cfg = {
        "state": args.state,
        "lang": args.lang,
        "year": args.year,
        "output": args.output,
        "concurrency": args.concurrency,
        "resume": args.resume,
        "dry_run": args.dry_run,
        "ac_filter": args.ac,
        "district_filters": args.district or [],  # empty = all districts
        "start_part": args.start_part,
        "end_part": args.end_part,
    }

    from downloader import run

    # Pre-flight confirmation for large downloads
    if not args.dry_run and not args.yes and not args.district and not args.ac:
        async with aiohttp.ClientSession() as session:
            acs = await get_constituencies(session, args.state)

        if acs and len(acs) > 10:
            districts = get_districts_from_ac_list(acs)
            print(
                f"  About to download ALL {len(districts)} districts "
                f"({len(acs)} ACs) for {state_name}."
            )
            print(f"  This could be tens of thousands of PDFs.")
            try:
                ans = input("  Continue? [Y/n] ").strip().lower()
                if ans and ans not in ("y", "yes"):
                    print("  Aborted.")
                    return
            except EOFError:
                pass

    try:
        await run(cfg)
    except KeyboardInterrupt:
        log.info("Interrupted -- progress has been saved.")
        print("\nInterrupted. Progress saved. Re-run with --resume to continue.")
    except OSError as exc:
        if "No space left" in str(exc) or "disk" in str(exc).lower():
            log.critical("Disk full: %s", exc)
            print(f"\nDisk full! Free some space and re-run with --resume.\n{exc}")
        else:
            raise


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nInterrupted. Progress saved. Re-run with --resume to continue.")
        sys.exit(1)


if __name__ == "__main__":
    main()
