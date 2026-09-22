"""Passwords and login cookies only — no heavy crypto imports.

The Vercel web app imports from here so its bundle stays small (no
cryptography/findmy/unicorn). Key encryption lives in security.py, which only
the poller and local scripts import.
"""

from __future__ import annotations

import hashlib

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import SECRET_KEY

# How long a login lasts. The cookie is signed, not encrypted, and there is no
# server-side session store, so the only way to bound a stolen cookie's life is
# to put the age in the signature and check it. 12 hours.
SESSION_MAX_AGE = 12 * 60 * 60


def _prep(plain: str) -> bytes:
    # bcrypt caps input at 72 bytes; pre-hash so long passwords still work.
    return hashlib.sha256(plain.encode("utf-8")).digest()


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_prep(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prep(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="session")


def make_session_cookie(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_cookie(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        data = _serializer.loads(raw, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("uid")
