"""Offline-safe teacher session handling.

Signs teacher_id into an HttpOnly cookie using itsdangerous.
No network, no SMTP, no external IdP required — works on a LAN-only school server.

The signing secret must be set via ALLPS_SESSION_SECRET in the environment.
If unset, a random secret is generated at boot (sessions survive restarts only
when the env var is set explicitly).
"""

from __future__ import annotations

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
