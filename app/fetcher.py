"""Poll Apple for all active trackers, decrypt reports, store new positions.

Runs on GitHub Actions (cron) in production, and can be run locally:
    python -m app.fetcher

Fetch strategy: for each tracker, generate every rolling key it could have
broadcast over the query window, ask Apple for reports on those keys, and
decrypt them. The Apple session is loaded from and saved back to the database.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .apple_account import load_account, save_account
from .db import SessionLocal
from .models import AppState, Position, Tracker
from .security import decrypt_keys
from .tag_store import _fix_future_pairing, accessory_from_json

log = logging.getLogger("fetcher")

_BATTERY = {0: "Full", 1: "Medium", 2: "Low", 3: "Very low"}
LOOKBACK_DAYS = 7
INDEX_BUFFER = 10
_LAST_FETCH_KEY = "last_fetch_at"


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


def _recently_fetched(db, within_seconds: int) -> bool:
    row = db.get(AppState, _LAST_FETCH_KEY)
    if not row:
        return False
    try:
        last = datetime.fromisoformat(row.value)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - last).total_seconds() < within_seconds


def _mark_fetched(db) -> None:
    row = db.get(AppState, _LAST_FETCH_KEY)
    stamp = datetime.now(timezone.utc).isoformat()
    if row is None:
        db.add(AppState(key=_LAST_FETCH_KEY, value=stamp))
    else:
        row.value = stamp
    db.commit()


def run_once(min_interval_seconds: int = 0) -> dict:
    """Fetch and store. If min_interval_seconds > 0 and a fetch happened more
    recently than that, skip (used to coalesce many web viewers into one poll).
    """
    db = SessionLocal()
    try:
        if min_interval_seconds and _recently_fetched(db, min_interval_seconds):
            log.info("Skipped: fetched within the last %ss.", min_interval_seconds)
            return {"trackers": 0, "new_positions": 0, "skipped": True}

        trackers = db.scalars(select(Tracker).where(Tracker.active == 1)).all()
        if not trackers:
            log.info("No active trackers to poll.")
            return {"trackers": 0, "new_positions": 0}

        apple = load_account(db)
        new_count = 0
        polled = 0

        for t in trackers:
            try:
                acc = accessory_from_json(decrypt_keys(t.encrypted_keys))
                _fix_future_pairing(acc)
            except Exception as e:  # noqa: BLE001
                log.error("Tracker %s: could not load keys: %s", t.id, e)
                continue

            keys = _keys_for(acc)
            log.info("Tracker %s (%s): querying %d keys...", t.id, t.name, len(keys))
            polled += 1

            try:
                result = apple.fetch_location_history(keys)
            except Exception as e:  # noqa: BLE001
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

        # Persist the (possibly refreshed) session and the fetch timestamp.
        try:
            save_account(db, apple)
        except Exception as e:  # noqa: BLE001
            log.error("Could not save refreshed Apple session: %s", e)
        _mark_fetched(db)

        log.info("Done. Stored %d new position(s).", new_count)
        return {"trackers": polled, "new_positions": new_count}
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_once())
