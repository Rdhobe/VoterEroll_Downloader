"""
ECI Electoral Roll Downloader — Captcha fetch + OCR solver

Uses ddddocr==1.5.5 EXACTLY (1.6.0 is broken).
"""

import base64
import logging
import threading

import aiohttp

from config import GATEWAY_API, HEADERS, REQUEST_TIMEOUT

log = logging.getLogger("eroll")


class CaptchaSolver:
    """Fetch a captcha from the ECI gateway and solve it with ddddocr."""

    _ocr = None
    _lock = threading.Lock()
    _classify_lock = threading.Lock()

    @classmethod
    def _get_ocr(cls):
        """Lazy-load a single shared ddddocr instance (thread-safe)."""
        if cls._ocr is None:
            with cls._lock:
                if cls._ocr is None:
                    import ddddocr

                    cls._ocr = ddddocr.DdddOcr(show_ad=False)
                    log.debug("ddddocr instance created")
        return cls._ocr

    async def fetch_and_solve(
        self, session: aiohttp.ClientSession
    ) -> tuple[str, str]:
        """
        1. GET /captcha-service/generateCaptcha/eroll
        2. Base64-decode the JPEG image
        3. Run ddddocr OCR
        4. Return (solved_text, captcha_id)

        Raises on network / decode failures — callers should handle.
        """
        url = f"{GATEWAY_API}/captcha-service/generateCaptcha/eroll"
        async with session.get(
            url,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        captcha_b64: str = data.get("captcha", "")
        captcha_id: str = data.get("id", "")

        if not captcha_b64 or not captcha_id:
            raise ValueError(f"Empty captcha response: {data}")

        image_bytes = base64.b64decode(captcha_b64)
        ocr = self._get_ocr()
        with self._classify_lock:
            solved = ocr.classification(image_bytes)
        solved = solved.strip().lower()

        log.debug("Captcha solved: '%s'  id=%s", solved, captcha_id[:12])
        return solved, captcha_id
