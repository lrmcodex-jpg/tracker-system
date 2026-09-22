"""Manage the fetching Apple session, stored in the database.

Storing the session in the DB (not a local file) is what lets the same login
work across your Mac, the GitHub Actions poller, and anywhere else — they all
share one database. The anisette native libs are cached to a temp dir and
downloaded on first use (fine on any full Linux/macOS environment; NOT on
Vercel, which is why the poller runs on GitHub Actions instead).
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path

from findmy import AppleAccount, LocalAnisetteProvider

log = logging.getLogger("apple")

_ACCOUNT_KEY = "apple_account"
_LIBS_PATH = Path(tempfile.gettempdir()) / "ani_libs.bin"


def load_account(db) -> AppleAccount:
    """Load the cached Apple session from the DB."""
    from .models import AppState

    row = db.get(AppState, _ACCOUNT_KEY)
    if row is None:
        raise RuntimeError(
            "No Apple session in the database. Run the one-time login first:\n"
            "    python -m app.setup_apple_login"
        )
    mapping = json.loads(row.value)
    return AppleAccount.from_json(mapping, anisette_libs_path=str(_LIBS_PATH))


def save_account(db, acc: AppleAccount) -> None:
    """Persist the (possibly refreshed) Apple session back to the DB."""
    from .models import AppState

    payload = json.dumps(acc.to_json())
    row = db.get(AppState, _ACCOUNT_KEY)
    if row is None:
        db.add(AppState(key=_ACCOUNT_KEY, value=payload))
    else:
        row.value = payload
    db.commit()


def anisette_provider() -> LocalAnisetteProvider:
    return LocalAnisetteProvider(libs_path=str(_LIBS_PATH))
