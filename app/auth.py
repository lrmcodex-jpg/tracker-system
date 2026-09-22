"""Passwords and login cookies only — no heavy crypto imports.

The Vercel web app imports from here so its bundle stays small (no
cryptography/findmy/unicorn). Key encryption lives in security.py, which only
the poller and local scripts import.
"""

from __future__ import annotations

import hashlib

import bcrypt
from itsdangerous import BadSignature, URLSafeSerializer

from .config import SECRET_KEY


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


_serializer = URLSafeSerializer(SECRET_KEY, salt="session")


def make_session_cookie(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_cookie(raw: str | None) -> int | None:
    if not raw:
        return None
    try:
        data = _serializer.loads(raw)
    except BadSignature:
        return None
    return data.get("uid")
