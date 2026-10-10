"""
ECI Electoral Roll Downloader — All ECI gateway API calls (metadata)
"""

import base64
import json
import logging
import os
from typing import Any

import aiohttp
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import load_der_public_key

from config import GATEWAY_API, HEADERS, REQUEST_TIMEOUT

log = logging.getLogger("eroll")

# ── Cryptographic Constants ──
PUBLIC_KEY_B64 = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEArb7++BxL/YN8OIln+6FL9Gnw5D"
    "NmQ/VFZXss+J+TuQyJc891JbqbijxYQNEin2c2u+CnpXpoGQ/1gUSzDMJeNS3sNSlIUykp"
    "2dt7xIm/cmV4sZ/c769vCxVRosMfRaZJnBAah+m1X26lEhnOo0wpAB9Txr8RIyBe6h7PiQ"
    "WykeJeh6UacOBBX28kgkq7+vJhW8HgB38lt32XRocznRYwS9LqR7ZweFmQhTr1+EGrqiEK"
    "COCxMYgHR2SQckb96hZ9kWzfzeun4bUO5oXKJciLkiS1IgKieADEvYLgu129ZIpn1H+8H"
    "+8ikNNVETqEDDMtqcQcQmWppJvcWHaXAs+f8QIDAQAB"
)
MIS_KEY = "EROLLA32DVI09AJH"


def base64url_encode(data: bytes) -> str:
    """Encode bytes to URL-safe base64 string without padding."""
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')


def encrypt_json_body(body: dict) -> dict[str, str]:
    """
    Encrypt a POST body the way the ECI web frontend does for
    get-publish-part-list: the whole JSON object is AES-256-GCM encrypted,
    the AES key is RSA-OAEP-SHA256 encrypted with ECI's public key, and all
    values use standard base64 (with padding).

    Returns {"encryptedPayload": ..., "encryptedKey": ..., "iv": ...}.

    NOTE: the plaintext layout (compact JSON of the full body dict) is
    inferred from observed ciphertext length (~146 JSON chars for a part-list
    request). If ECI returns 400, the layout guess needs revisiting.
    """
    aes_key = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    aesgcm = AESGCM(aes_key)

    plaintext = json.dumps(body, separators=(",", ":")).encode("utf-8")
    enc_payload = aesgcm.encrypt(iv, plaintext, None)

    der_data = base64.b64decode(PUBLIC_KEY_B64)
    public_key = load_der_public_key(der_data)
    enc_aes_key = public_key.encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )

    return {
        "encryptedPayload": base64.b64encode(enc_payload).decode("utf-8"),
        "encryptedKey": base64.b64encode(enc_aes_key).decode("utf-8"),
        "iv": base64.b64encode(iv).decode("utf-8"),
    }


def encrypt_payloads(state_cd: str, year: int) -> tuple[str, str, str, str, str]:
    """
    Encrypt stateCd, year, and misKey using ECI's AES-256-GCM + RSA-OAEP hybrid encryption.
    Returns: accept_yek, accept_rotcev, param_state, param_year, param_mis_key
    """
    aes_key = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    aesgcm = AESGCM(aes_key)

    state_json = json.dumps(state_cd).encode('utf-8')
    year_json = json.dumps(year).encode('utf-8')
    mis_key_json = json.dumps(MIS_KEY).encode('utf-8')

    enc_state = aesgcm.encrypt(iv, state_json, None)
    enc_year = aesgcm.encrypt(iv, year_json, None)
    enc_mis_key = aesgcm.encrypt(iv, mis_key_json, None)

    der_data = base64.b64decode(PUBLIC_KEY_B64)
    public_key = load_der_public_key(der_data)

    enc_aes_key = public_key.encrypt(
        aes_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None
        )
    )

    accept_yek = base64url_encode(enc_aes_key)
    accept_rotcev = base64url_encode(iv)
    param_state = base64url_encode(enc_state)
    param_year = base64url_encode(enc_year)
    param_mis_key = base64url_encode(enc_mis_key)

    return accept_yek, accept_rotcev, param_state, param_year, param_mis_key


async def _get(
    session: aiohttp.ClientSession,
    path: str,
    extra_headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None
) -> dict[str, Any] | list[Any]:
    """Perform a GET request and return parsed JSON."""
    url = f"{GATEWAY_API}/{path}"
    log.debug("GET %s  params=%s", url, params)
    
    req_headers = HEADERS.copy()
    if extra_headers:
        req_headers.update(extra_headers)
        
    async with session.get(
        url,
        headers=req_headers,
        params=params,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


async def _post(
    session: aiohttp.ClientSession, path: str, body: dict
) -> dict[str, Any]:
    """Perform a POST request and return parsed JSON."""
    url = f"{GATEWAY_API}/{path}"
    log.debug("POST %s  body=%s", url, body)
    async with session.post(
        url,
        headers=HEADERS,
        json=body,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
    ) as resp:
        response_text = await resp.text()

        if resp.status >= 400:
            log.error(
                "ECI POST ERROR %s | status=%s | response=%s",
                url,
                resp.status,
                response_text[:2000],
            )
            resp.raise_for_status()

        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            log.error(
                "ECI returned non-JSON response: %s",
                response_text[:2000],
            )
            raise


# ── Endpoint 1 — Roll type metadata ─────────────────────────────────────
async def get_roll_types(
    session: aiohttp.ClientSession, state_cd: str, year: int
) -> list[dict]:
    """
    GET /printing-publish/get-publish-eroll-type?stateCd=…&year=…
    Returns only entries where publish == "Y".
    """
    accept_yek, accept_rotcev, param_state, param_year, param_mis_key = encrypt_payloads(
        state_cd, year
    )

    extra_headers = {
        "accept_yek": accept_yek,
        "accept_rotcev": accept_rotcev
    }
    params = {
        "stateCd": param_state,
        "year": param_year,
        "misKey": param_mis_key
    }

    data = await _get(
        session,
        "printing-publish/get-publish-eroll-type",
        extra_headers=extra_headers,
        params=params,
    )
    payload = data.get("payload", [])
    if not isinstance(payload, list):
        log.error("Unexpected roll-type response: %s", data)
        return []
    return [r for r in payload if r.get("publish") == "Y"]



# ── Endpoint 2 — Assembly Constituencies ────────────────────────────────
async def get_constituencies(
    session: aiohttp.ClientSession, state_cd: str
) -> list[dict]:
    """
    GET /common/constituencies?stateCode=…
    Returns the raw AC list (direct array).
    """
    data = await _get(session, f"common/constituencies?stateCode={state_cd}")
    if not isinstance(data, list):
        log.error("Unexpected constituencies response: %s", data)
        return []
    return data


# ── Endpoint 3 — Part list for one AC ───────────────────────────────────
async def get_part_list(
    session: aiohttp.ClientSession,
    state_cd: str,
    ac_number: int,
    year: int,
    roll_type: str,
    roll_type_ref_id: str,
    pdf_gen_type: str,
    revision_no: int,
) -> list[int]:
    """
    POST /printing-publish/get-publish-part-list
    Returns a sorted list of part numbers.

    The body must be AES+RSA encrypted (see encrypt_json_body) — plain JSON
    is rejected with an empty 400.
    """
    body = {
        "stateCd": state_cd,
        "acNumber": ac_number,
        "year": year,
        "rollType": roll_type,
        "rollTypeRefId": roll_type_ref_id,
        "pdfGenType": pdf_gen_type,
        "revisionNo": revision_no,
    }
    try:
        data = await _post(
            session, "printing-publish/get-publish-part-list", encrypt_json_body(body)
        )
    except Exception:
        # Encrypted layout not yet matching the frontend — retry legacy plain JSON.
        log.debug("Encrypted part-list failed, retrying plain JSON for AC %s", ac_number)
        data = await _post(session, "printing-publish/get-publish-part-list", body)
    payload = data.get("payload", [])
    if not isinstance(payload, list):
        log.error("Unexpected part-list response for AC %s: %s", ac_number, data)
        return []
    return sorted(p["partNumber"] for p in payload if "partNumber" in p)


# ── Endpoint 4 — Languages for an AC ────────────────────────────────────
async def get_ac_languages(
    session: aiohttp.ClientSession,
    state_cd: str,
    ac_number: int,
    roll_type_ref_id: str,
    pdf_gen_type: str,
) -> dict[str, str]:
    """
    POST /printing-publish/get-ac-languages
    Returns e.g. {"ENG": "ENGLISH", "TAM": "TAMIL"}.
    """
    body = {
        "stateCd": state_cd,
        "acNumber": ac_number,
        "rollTypeRefId": roll_type_ref_id,
        "pdfGenType": pdf_gen_type,
    }
    data = await _post(session, "printing-publish/get-ac-languages", body)
    payload = data.get("payload", {})
    if not isinstance(payload, dict):
        log.error("Unexpected languages response for AC %s: %s", ac_number, data)
        return {}
    return payload
