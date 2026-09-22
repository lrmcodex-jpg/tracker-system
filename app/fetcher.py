"""Poll Apple for all active trackers, decrypt reports, store new positions."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .apple_account import load_account
from .db import SessionLocal
from .models import Position, Tracker
from .security import decrypt_keys
from .tag_store import _fix_future_pairing, accessory_from_json

log = logging.getLogger("fetcher")

_BATTERY = {0: "Full", 1: "Medium", 2: "Low", 3: "Very low"}
LOOKBACK_DAYS = 7
INDEX_BUFFER = 10


def _battery(status: int) -> str:
    return _BATTERY.get((status >> 6) & 0b11, "Unknown")


def _keys_for(acc) -> list:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=LOOKBACK_DAYS)
    lo = max(0, acc.get_min_index(start))
    hi = acc.get_max_index(now) + INDEX_BUFFER
    keys = []
    for i in range(lo, hi + 1):
        keys.extend(acc.keys_at(i))
    return list(dict.fromkeys(keys))


def run_once() -> dict:
    db = SessionLocal()
    try:
        trackers = db.scalars(select(Tracker).where(Tracker.active == 1)).all()
        if not trackers:
            log.info("No active trackers to poll.")
            return {"trackers": 0, "new_positions": 0}

        apple = load_account()
        new_count = 0
        polled = 0

        for t in trackers:
            try:
                acc = accessory_from_json(decrypt_keys(t.encrypted_keys))
                _fix_future_pairing(acc)
            except Exception as e:
                log.error("Tracker %s: could not load keys: %s", t.id, e)
                continue

            keys = _keys_for(acc)
            log.info("Tracker %s (%s): querying %d keys...", t.id, t.name, len(keys))
            polled += 1

            try:
                result = apple.fetch_location_history(keys)
            except Exception as e:
                log.error("Tracker %s: fetch failed: %s", t.id, e)
                continue

            reports = []
            if isinstance(result, dict):
                for rs in result.values():
                    reports.extend(rs or [])
            elif result:
                reports = list(result)

            log.info("Tracker %s: %d report(s) from Apple.", t.id, len(reports))

            for r in reports:
                try:
                    lat, lon = r.latitude, r.longitude
                except Exception:
                    continue
                ts = r.timestamp.astimezone(timezone.utc).replace(tzinfo=None)
                db.add(Position(
                    tracker_id=t.id, latitude=lat, longitude=lon,
                    accuracy_m=r.horizontal_accuracy, battery=_battery(r.status),
                    reported_at=ts,
                ))
                try:
                    db.commit()
                    new_count += 1
                except IntegrityError:
                    db.rollback()

        log.info("Done. Stored %d new position(s).", new_count)
        return {"trackers": polled, "new_positions": new_count}
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_once())
