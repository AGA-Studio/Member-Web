"""Cloudflare Turnstile check for the login (wiki: "Servicios de terceros").

- `TURNSTILE_ENABLED` off (development, CI, offline demo): every login passes and
  the network is never touched.
- On: one `POST` to `siteverify` with a 5 s timeout. It passes only when
  Cloudflare answers `success` for the frontend's hostname. Anything else (no
  token, bad token, Cloudflare down or slow) fails: fail-closed.

`remoteip` is never sent. Behind Cloudflare and Coolify uvicorn trusts any
`X-Forwarded-For` (`--forwarded-allow-ips '*'` in docker/entrypoint.sh), so the
client IP is not trustworthy, and `siteverify` works without it.

The secret is never logged; only Cloudflare's `error-codes` are.
"""

import logging

import httpx

from core.config import settings

TIMEOUT_SECONDS = 5.0
# Cloudflare rejects longer tokens; no need to send them.
MAX_TOKEN_LENGTH = 2048

# uvicorn's logger is the one that reaches the console when the API runs.
logger = logging.getLogger("uvicorn.error")

# HTTP transport used for `siteverify`. None = the real network. Tests replace it
# with an `httpx.MockTransport` that answers like Cloudflare.
_transport: httpx.BaseTransport | None = None


def verify_turnstile(token: str | None) -> bool:
    """True when the login may go on: Turnstile is off, or the token is valid."""
    if not settings.turnstile_enabled:
        return True
    if not token or len(token) > MAX_TOKEN_LENGTH:
        logger.warning("Turnstile failed: missing or oversized token")
        return False

    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, transport=_transport) as client:
            response = client.post(
                settings.turnstile_siteverify_url,
                data={"secret": settings.turnstile_secret, "response": token},
            )
            response.raise_for_status()
            result = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Turnstile failed: siteverify unavailable (%s)", type(exc).__name__)
        return False

    if not isinstance(result, dict) or result.get("success") is not True:
        codes = result.get("error-codes") if isinstance(result, dict) else None
        logger.warning("Turnstile failed: error-codes=%s", codes)
        return False
    if result.get("hostname") != settings.turnstile_hostname:
        logger.warning("Turnstile failed: unexpected hostname %r", result.get("hostname"))
        return False
    return True
