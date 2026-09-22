"""Configuration, read from environment variables (.env is loaded on startup)."""

from __future__ import annotations

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Minimal .env loader so we don't add a dependency."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

# --- Database ---------------------------------------------------------------
# MySQL in production. Falls back to a local SQLite file if DB_URL is unset,
# so you can try the app with zero setup before wiring up MySQL.
DB_URL = os.environ.get(
    "DB_URL",
    "sqlite:///" + str(Path(__file__).resolve().parent.parent / "tracker.db"),
)

# Normalize Supabase/Heroku-style URLs to the psycopg (v3) driver.
if DB_URL.startswith("postgres://"):
    DB_URL = "postgresql+psycopg://" + DB_URL[len("postgres://"):]
elif DB_URL.startswith("postgresql://"):
    DB_URL = "postgresql+psycopg://" + DB_URL[len("postgresql://"):]

# --- Secrets ----------------------------------------------------------------
# SECRET_KEY signs the login cookie. KEY_ENCRYPTION_KEY encrypts tag keys at
# rest. BOTH must be set to fixed values in production (see .env.example).
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
KEY_ENCRYPTION_KEY = os.environ.get("KEY_ENCRYPTION_KEY", "")

# --- Apple fetching account -------------------------------------------------
# The disposable Apple ID used only to pull location reports.
APPLE_ID = os.environ.get("APPLE_ID", "")
APPLE_PASSWORD = os.environ.get("APPLE_PASSWORD", "")
# Where the cached Apple session + anisette libs live (created on first login).
DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
ACCOUNT_FILE = DATA_DIR / "account.json"
ANISETTE_LIBS = DATA_DIR / "ani_libs.bin"

# --- Fetcher ----------------------------------------------------------------
# How often to poll Apple, in minutes. Reports are delayed/batched anyway, so
# going below ~10 wastes requests and raises the ban risk.
POLL_INTERVAL_MIN = int(os.environ.get("POLL_INTERVAL_MIN", "15"))
