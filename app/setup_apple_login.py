"""One-time interactive login for the fetching Apple ID.

Run once on the server:   python -m app.setup_apple_login

It signs in (asking for the 2FA code), then saves the session so the fetcher
can run on its own afterwards. Uses APPLE_ID / APPLE_PASSWORD from .env if set,
otherwise prompts.
"""

from __future__ import annotations

import getpass
import sys

from findmy import (
    AppleAccount,
    LocalAnisetteProvider,
    LoginState,
    SmsSecondFactorMethod,
    TrustedDeviceSecondFactorMethod,
)

from .config import ACCOUNT_FILE, ANISETTE_LIBS, APPLE_ID, APPLE_PASSWORD


def main() -> int:
    if ACCOUNT_FILE.exists():
        ans = input(f"A session already exists at {ACCOUNT_FILE}. Overwrite? [y/N] ")
        if ans.strip().lower() != "y":
            print("Kept existing session.")
            return 0

    print("First-time Apple login for the FETCHING account (the disposable one).\n")
    acc = AppleAccount(LocalAnisetteProvider(libs_path=str(ANISETTE_LIBS)))

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

    acc.to_json(str(ACCOUNT_FILE))
    print(f"\nLogged in as {acc.account_name}. Session saved to {ACCOUNT_FILE}.")
    print("The fetcher can now run unattended.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
