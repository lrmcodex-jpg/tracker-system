"""Import a tracker from an OpenTagViewer export .zip into the database.

Run locally, pointed at the same DB_URL as the website/poller:
    python -m app.add_tracker /path/to/export.zip [client_id]

It asks for the export passcode. Every tag in the zip is imported (keys
encrypted at rest). Adding a tag is occasional, so it stays a local command
rather than something the serverless website does.
"""

from __future__ import annotations

import getpass
import sys

from .db import Base, SessionLocal, engine
from . import models  # noqa: F401
from .models import Client, Tracker
from .security import encrypt_keys
from .tag_store import load_accessories


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m app.add_tracker <export.zip> [client_id]")
        return 1
    zip_path = sys.argv[1]
    client_id = int(sys.argv[2]) if len(sys.argv) > 2 else None

    with open(zip_path, "rb") as f:
        data = f.read()
    passcode = getpass.getpass("Export passcode (hidden): ")

    try:
        accessories = load_accessories(data, passcode)
    except Exception as e:  # noqa: BLE001
        print(f"Import failed: {e}")
        return 1

    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        if client_id is not None and db.get(Client, client_id) is None:
            print(f"Warning: client_id {client_id} not found; importing unassigned.")
            client_id = None

        added, skipped = 0, 0
        for identifier, name, keys_json in accessories:
            if db.query(Tracker).filter(Tracker.identifier == identifier).first():
                skipped += 1
                continue
            db.add(Tracker(
                name=name, identifier=identifier, client_id=client_id,
                active=1, encrypted_keys=encrypt_keys(keys_json),
            ))
            added += 1
        db.commit()
        print(f"Imported {added} tracker(s)." + (f" Skipped {skipped} already present." if skipped else ""))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
