"""Offline-safe teacher session handling.

Signs teacher_id into an HttpOnly cookie using itsdangerous.
No network, no SMTP, no external IdP required — works on a LAN-only school server.

The signing secret must be set via ALLPS_SESSION_SECRET in the environment.
If unset, a random secret is generated at boot (sessions survive restarts only
when the env var is set explicitly).
"""

from __future__ import annotations

import hmac
import os
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

COOKIE_NAME = "allps_session"
SESSION_MAX_AGE = 60 * 60 * 12  # 12 hours

_secret: str | None = None


def _get_secret() -> str:
    global _secret
    if _secret is None:
        _secret = os.environ.get("ALLPS_SESSION_SECRET") or secrets.token_hex(32)
    return _secret


def make_session_cookie(teacher_id: str) -> str:
    """Return a signed token encoding teacher_id."""
    s = URLSafeTimedSerializer(_get_secret(), salt="allps-session")
    return s.dumps(teacher_id)


def read_session_cookie(token: str) -> str | None:
    """Verify and decode a session cookie.  Returns teacher_id or None if invalid/expired."""
    s = URLSafeTimedSerializer(_get_secret(), salt="allps-session")
    try:
        return s.loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def hash_pin(pin: str) -> str:
    """Return a bcrypt hash of a PIN."""
    import bcrypt
    return bcrypt.hashpw(pin.encode(), bcrypt.gensalt()).decode()


def verify_pin(pin: str, hashed: str) -> bool:
    """Return True if pin matches the stored bcrypt hash."""
    import bcrypt
    try:
        return bcrypt.checkpw(pin.encode(), hashed.encode())
    except Exception:
        return False


def get_ingest_api_key(explicit_key: str | None = None) -> str | None:
    """Return configured external ingestion API key, or None if unconfigured."""
    raw = explicit_key if explicit_key is not None else os.environ.get("ALLPS_INGEST_API_KEY")
    if not raw or not isinstance(raw, str):
        return None
    stripped = raw.strip()
    return stripped or None


def extract_api_key_from_headers(
    authorization: str | None = None,
    x_api_key: str | None = None,
) -> str | None:
    """Extract an API key from X-API-Key or Authorization: Bearer <token>."""
    if x_api_key and x_api_key.strip():
        return x_api_key.strip()
    if authorization:
        parts = authorization.strip().split(" ", 1)
        if len(parts) == 2 and parts[0].lower() == "bearer" and parts[1].strip():
            return parts[1].strip()
    return None


def verify_ingest_api_key(supplied_key: str | None, expected_key: str | None) -> bool:
    """Constant-time verification of an external ingestion API key."""
    if not supplied_key or not expected_key:
        return False
    return hmac.compare_digest(supplied_key.encode("utf-8"), expected_key.encode("utf-8"))
