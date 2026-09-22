"""Key encryption at rest (used by the poller and local scripts only).

Password/cookie helpers now live in auth.py (no heavy imports). They are
re-exported here so existing imports (app.main) keep working.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet

from .config import KEY_ENCRYPTION_KEY

# Re-export auth helpers for backward compatibility.
from .auth import (  # noqa: F401
    hash_password,
    make_session_cookie,
    read_session_cookie,
    verify_password,
)


def _fernet() -> Fernet:
    if not KEY_ENCRYPTION_KEY:
        raise RuntimeError(
            "KEY_ENCRYPTION_KEY is not set. Generate one and put it in .env "
            "(see .env.example). Without it, tag keys cannot be encrypted."
        )
    try:
        Fernet(KEY_ENCRYPTION_KEY.encode())
        return Fernet(KEY_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError):
        digest = hashlib.sha256(KEY_ENCRYPTION_KEY.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_keys(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_keys(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
