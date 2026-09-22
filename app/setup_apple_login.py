"""One-time interactive Apple login. Saves the session to the DATABASE.

Run once, locally (needs the 2FA code):
    python -m app.setup_apple_login

Point it at the SAME database the poller/website use (set DB_URL in .env to the
cloud MySQL). The session it stores is then usable by GitHub Actions.
"""

from __future__ import annotations

import getpass
import sys

from findmy import (
    AppleAccount,
    LoginState,
    SmsSecondFactorMethod,
    TrustedDeviceSecondFactorMethod,
)

from .apple_account import anisette_provider, save_account
from .config import APPLE_ID, APPLE_PASSWORD
from .db import Base, SessionLocal, engine
from . import models  # noqa: F401  (register tables)


def main() -> int:
    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        from .models import AppState
        if db.get(AppState, "apple_account") is not None:
            ans = input("A session already exists in the DB. Overwrite? [y/N] ")
            if ans.strip().lower() != "y":
                print("Kept existing session.")
                return 0

        print("First-time Apple login for the FETCHING account (the disposable one).\n")
        acc = AppleAccount(anisette_provider())

        email = APPLE_ID or input("Apple ID email: ").strip()
        password = APPLE_PASSWORD or getpass.getpass("Apple ID password (hidden): ")

        state = acc.login(email, password)
        if state == LoginState.REQUIRE_2FA:
            methods = acc.get_2fa_methods()
            print("\nWhere should Apple send the code?")
            for i, m in enumerate(methods):
                if isinstance(m, TrustedDeviceSecondFactorMethod):
                    print(f"  {i} - Apple devices (popup)")
                elif isinstance(m, SmsSecondFactorMethod):
                    print(f"  {i} - SMS to {m.phone_number}")
            choice = int(input("Number: ").strip() or 0)
            method = methods[choice]
            method.request()
            method.submit(input("6-digit code: ").strip())

        if acc.login_state != LoginState.LOGGED_IN:
            print(f"Login did not complete (state: {acc.login_state}).")
            return 1

        save_account(db, acc)
        print(f"\nLogged in as {acc.account_name}. Session saved to the database.")
        print("GitHub Actions can now poll unattended.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
