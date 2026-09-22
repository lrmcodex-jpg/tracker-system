"""Manage the single Apple account used to fetch location reports.

The account session is cached to disk (ACCOUNT_FILE) after the first login so
the fetcher can run unattended. The FIRST login needs a 2FA code and must be
done interactively once, using the setup script (setup_apple_login.py).
"""

from __future__ import annotations

import logging

from findmy import AppleAccount, LocalAnisetteProvider

from .config import ACCOUNT_FILE, ANISETTE_LIBS

log = logging.getLogger("apple")


def load_account() -> AppleAccount:
    """Load the cached Apple session. Raises if the first-time login hasn't run."""
    if not ACCOUNT_FILE.exists():
        raise RuntimeError(
            "No Apple session found. Run the one-time login first:\n"
            "    python -m app.setup_apple_login"
        )
    return AppleAccount.from_json(str(ACCOUNT_FILE), anisette_libs_path=str(ANISETTE_LIBS))


def save_account(acc: AppleAccount) -> None:
    acc.to_json(str(ACCOUNT_FILE))
