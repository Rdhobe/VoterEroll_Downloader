"""
ECI Electoral Roll Downloader — Configuration & Constants
"""

# ── API ──────────────────────────────────────────────────────────────────
GATEWAY_API = "https://gateway-voters.eci.gov.in/api/v1"
FRONTEND_URL = "https://voters.eci.gov.in/download-eroll"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://voters.eci.gov.in/",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://voters.eci.gov.in",
    "Content-Type": "application/json",
    "applicationName": "VSP",
    "PLATFORM-TYPE": "ECIWEB",
    "channelidobo": "VSP",
}

# Direct ZIP download base URL (no captcha/auth needed)
EROLL_DIRECT_URL = "https://voters.eci.gov.in/eroll"

# External gateway for downloading generated PDFs (no auth needed)
GATEWAY_EXT_API = "https://gateway-vpd.eci.gov.in/api/v1"

# Headers for the external API (different from main gateway)
EXT_HEADERS = {
    "applicationName": "VSP",
    "CurrentRole": "citizen",
    "Accept": "application/json",
    "channelidobo": "VSP",
    "PLATFORM-TYPE": "ECIWEB",
}

# ── Defaults ─────────────────────────────────────────────────────────────
DEFAULT_STATE = "S22"
DEFAULT_LANG = "ENG"
DEFAULT_YEAR = 2026
DEFAULT_CONCURRENCY = 20

# ── Retry / back-off ────────────────────────────────────────────────────
MAX_CAPTCHA_ATTEMPTS = 8
MAX_NETWORK_RETRIES = 3
BACKOFF_BASE = 2        # seconds
BACKOFF_MAX = 60        # seconds
REQUEST_TIMEOUT = 30    # seconds

# ── State code → human name ─────────────────────────────────────────────
STATE_NAMES = {
    "S01": "Andhra Pradesh",
    "S03": "Assam",
    "S04": "Bihar",
    "S06": "Gujarat",
    "S07": "Haryana",
    "S10": "Karnataka",
    "S11": "Kerala",
    "S12": "Madhya Pradesh",
    "S13": "Maharashtra",
    "S18": "Odisha",
    "S19": "Punjab",
    "S20": "Rajasthan",
    "S22": "Tamil Nadu",
    "S24": "Uttar Pradesh",
    "S25": "West Bengal",
    "S26": "Chhattisgarh",
    "S27": "Jharkhand",
    "S28": "Uttarakhand",
    "S29": "Telangana",
    "U05": "NCT of Delhi",
}

# ── Language code → human name ──────────────────────────────────────────
LANG_MAP = {
    "ENG": "ENGLISH",
    "TAM": "TAMIL",
    "HIN": "HINDI",
    "BEN": "BENGALI",
    "KAN": "KANNADA",
    "MAL": "MALAYALAM",
    "TEL": "TELUGU",
    "MAR": "MARATHI",
    "GUJ": "GUJARATI",
    "PAN": "PUNJABI",
}
