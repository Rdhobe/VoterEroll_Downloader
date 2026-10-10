# ECI Electoral Roll PDF Downloader (UP / Hindi / 2026)

Bulk-download Electoral Roll PDFs (voter lists) for **Uttar Pradesh (S24), Hindi (HIN), SIR FinalRoll 2026** from `voters.eci.gov.in` using direct async HTTP — no browser needed.

> Verified working: byte-identical output to browser downloads. Tested district runs complete 3,000–4,000 parts (~20 GB) in ~30 min at ~115 parts/min when ECI isn't throttling.

## Installation (local)

```powershell
cd C:\projects\VoterEroll_Downloader
python -m venv .venv
.\.venv\Scripts\Activate.ps1
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> `ddddocr` must stay at **1.5.5** exactly (pinned in requirements.txt).

## Standard workflow (district by district)

```powershell
# 1. Preview a district (no downloading)
.\.venv\Scripts\python.exe main.py --state S24 --lang HIN --year 2026 --district Agra --dry-run --yes --output "G:\Election_Download"

# 2. Download it (restart-safe)
.\.venv\Scripts\python.exe main.py --state S24 --lang HIN --year 2026 --district Agra --resume --yes --output "G:\Election_Download"
```

`--resume` must always pair with the **same** `--output` path, or progress tracking restarts from zero.

## Before every run: the 5-second throttle test

ECI throttles aggressively after sustained downloading (symptoms: <1 part/s, mass `X` failures). Test first:

```powershell
curl.exe -o NUL -w "%{http_code} %{time_total}s %{size_download}b`n" "https://voters.eci.gov.in/eroll/2026/s24/sir-finalroll/118/2026-EROLLGEN-S24-118-SIR-FinalRoll-Revision1-HIN-2-WI.pdf" --max-time 60
```

* `200` in under ~5 s → run, preferably with `--concurrency 5` (10 max).
* Slow/timeout → **do not run**. Wait hours, or switch to mobile hotspot (different IP) and re-test there. Throttled runs never recover mid-run — `Ctrl+C` immediately if speed collapses.

## District names: ECI quirks

The `--district` filter is a substring match against ECI's names, which differ from common names. Use the **code** (right column) to be exact:

| You mean | Use | Why |
|---|---|---|
| Ambedkar Nagar | `--district S2470` | ECI calls it **Akbarpur**; plain `Akbarpur` also matches `Akbarpur - Raniya` (different district) |
| Ballia | `--district Bairia` (or `S2449`) | All 7 Ballia ACs sit under code S2449 named Bairia |
| Auraiya | `--district Auraiya` | commonly misspelled "Auriya" |
| Bareilly | `--district Bareilly` | commonly misspelled "Bareily" |

Output folders use ECI's names (e.g. `Akbarpur/`, `Bairia/`) — that's expected.

## CLI arguments

| Argument | Default | Notes |
|---|---|---|
| `--state` | `S22` | Always pass `S24` here |
| `--lang` | `ENG` | Always pass `HIN` here |
| `--year` | `2026` | Roll year |
| `--output` | `output_finalroll` | Use `G:\Election_Download` (full UP needs ~1 TB; keep ~25 GB free per district) |
| `--district` | *(all)* | Substring match — prefer district **codes** (see table) |
| `--ac` | *(all)* | Single AC number, e.g. `--ac 86` for testing |
| `--concurrency` | `20` | Downloads cap at 10 internally; use 5–10 under throttle |
| `--resume` | off | Skip completed parts (reads per-AC `status.json`) |
| `--dry-run` | off | Probe + plan only, downloads nothing |
| `--list-districts` | off | List districts and exit |
| `--yes` / `-y` | off | Skip the full-state confirmation prompt |

Full state (no `--district`/`--ac`) = 75 districts, 403 ACs, ~175,000 PDFs, ~1 TB, ~30 h. Do it district-by-district instead.

## Output structure

```
G:\Election_Download\
└── Uttar_Pradesh/
    └── Agra/
        ├── AC_86_Etmadpur/
        │   ├── status.json        # completed part numbers (resume state)
        │   ├── failed.json        # parts failing all strategies (retried on resume)
        │   └── 2026-EROLLGEN-S24-86-SIR-FinalRoll-Revision1-HIN-1-WI.pdf
        └── AC_87_Agra_Cantt./
```

## How it works (internals)

1. **Roll selection**: picks `SIR FinalRoll / EROLLGEN / rev 1` (never the default first entry, Supplement-2, which has no CDN files).
2. **Part discovery**: `get-publish-part-list` API (encrypted + plain attempts) → falls back to **CDN probing** with plain GET (`HEAD` gets `406` on ECI's CDN; slug is `sir-finalroll`).
3. **Download**: pre-generated PDFs straight from the CDN, no captcha. Captcha fallback fails fast (5 attempts) since the captcha endpoint returns `404` for scripts.
4. Failed parts land in per-AC `failed.json` and are retried on the next `--resume` run.

## Troubleshooting

| Symptom | Cause → Fix |
|---|---|
| `No districts match the given filters` | ECI naming quirk → use code from table above |
| Mass `X` failures + ~5–15 s/part | IP throttled → stop, cool off hours, curl-test, resume with `--concurrency 5` |
| Probe finds far fewer parts than expected (e.g. 31 vs ~440) | Throttled probe miscounts timeouts as misses → re-probe later; resume self-heals |
| One part hangs the run | Fixed: captcha retries are capped at 5, then the part fails fast |
| `400`/`500` lines from `get-publish-part-list` | Expected noise — the CDN probe covers part discovery |
| Log `stopping after 40 consecutive misses` | Cosmetic double-count in the message; stopping behavior is correct |
