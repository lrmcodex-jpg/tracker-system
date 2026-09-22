"""Password hashing, login sessions, and encryption of tag keys at rest."""

from __future__ import annotations

import base64
import hashlib

import bcrypt
from cryptography.fernet import Fernet
from itsdangerous import BadSignature, URLSafeSerializer

from .config import KEY_ENCRYPTION_KEY, SECRET_KEY

# --- Passwords --------------------------------------------------------------
# bcrypt caps input at 72 bytes; pre-hash so long passwords still work.
def _prep(plain: str) -> bytes:
    return hashlib.sha256(plain.encode("utf-8")).digest()


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_prep(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(_prep(plain), hashed.encode("utf-8"))
    except ValueError:
        return False


# --- Login cookie (signed, not encrypted) -----------------------------------
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


# --- Tag key encryption -----------------------------------------------------
def _fernet() -> Fernet:
    """Build a Fernet cipher from KEY_ENCRYPTION_KEY.

    Accepts either a proper 32-byte urlsafe-base64 key, or any passphrase
    (which we hash to the right length). A dedicated generated key is best.
    """
    if not KEY_ENCRYPTION_KEY:
        raise RuntimeError(
            "KEY_ENCRYPTION_KEY is not set. Generate one and put it in .env "
            "(see .env.example). Without it, tag keys cannot be encrypted."
        )
    try:
        # Is it already a valid Fernet key?
        Fernet(KEY_ENCRYPTION_KEY.encode())
        return Fernet(KEY_ENCRYPTION_KEY.encode())
    except (ValueError, TypeError):
        # Treat it as a passphrase: derive a 32-byte key from it.
        digest = hashlib.sha256(KEY_ENCRYPTION_KEY.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_keys(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_keys(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode()).decode()
