"""Turn an OpenTagViewer export .zip into per-tag Find My key objects.

The export contains, per tag:
  OwnedBeacons/<uuid>.plist                 <- key material
  BeaconNamingRecord/<uuid>/<uuid>.plist    <- the name
  KeyAlignmentRecords/<uuid>/<uuid>.plist   <- optional, improves accuracy

We load each into a findmy.FindMyAccessory, then serialise it to JSON with
to_json(). That JSON is what we encrypt and store in the database.
"""

from __future__ import annotations

import plistlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyzipper
from findmy import FindMyAccessory


def normalise_passcode(raw: str) -> str:
    """Accept the export passcode however it was written (hyphens, case, I/O/L)."""
    code = "".join(ch for ch in raw.upper() if ch not in " -_\t\r\n")
    return code.translate(str.maketrans({"I": "1", "L": "1", "O": "0"}))


def _read_zip(zip_bytes: bytes, passcode: str | None) -> dict[str, bytes]:
    import io

    with pyzipper.AESZipFile(io.BytesIO(zip_bytes)) as zf:
        encrypted = any(info.flag_bits & 0x1 for info in zf.infolist())
        if encrypted:
            if not passcode:
                raise ValueError("This export is passcode-protected; a passcode is required.")
            zf.setpassword(normalise_passcode(passcode).encode())
        try:
            return {n: zf.read(n) for n in zf.namelist() if not n.endswith("/")}
        except RuntimeError as e:
            raise ValueError("Wrong passcode for this export.") from e


def load_accessories(zip_bytes: bytes, passcode: str | None) -> list[tuple[str, str, str]]:
    """Return a list of (identifier, name, keys_json) for every tag in the zip."""
    files = _read_zip(zip_bytes, passcode)

    beacons = {
        n: d for n, d in files.items()
        if n.startswith("OwnedBeacons/") and n.endswith(".plist")
    }
    if not beacons:
        raise ValueError("No tags found in this export (no OwnedBeacons records).")

    out: list[tuple[str, str, str]] = []
    for path, data in beacons.items():
        beacon_id = Path(path).stem

        name = None
        for n, d in files.items():
            if n.startswith(f"BeaconNamingRecord/{beacon_id}/"):
                try:
                    name = plistlib.loads(d).get("name")
                except Exception:
                    name = None
                break

        alignment = next(
            (d for n, d in files.items() if n.startswith(f"KeyAlignmentRecords/{beacon_id}/")),
            None,
        )

        acc = FindMyAccessory.from_plist(data, alignment, name=name or beacon_id)
        _fix_future_pairing(acc)
        keys_json = _to_json_str(acc)
        out.append((acc.identifier or beacon_id, acc.name or beacon_id, keys_json))
    return out


def _to_json_str(acc: FindMyAccessory) -> str:
    """FindMyAccessory.to_json returns a dict; serialise it to a JSON string."""
    import json

    return json.dumps(acc.to_json())


def accessory_from_json(keys_json: str) -> FindMyAccessory:
    """Rebuild a FindMyAccessory from stored JSON (for fetching)."""
    import json

    return FindMyAccessory.from_json(json.loads(keys_json))


def _fix_future_pairing(acc) -> None:
    """Re-anchor a tag whose pairing/alignment date is in the future.

    Exports can store the pairing time in local tz but it is read as UTC,
    pushing the key-index anchor hours ahead of now. The fetcher then scans
    the wrong key indices and gets 0 reports even when Find My shows a
    location. If the anchor is at/after now, move it safely into the past so
    the fetcher scans a wide positive index range covering the last week.
    """
    now = datetime.now(timezone.utc)
    try:
        anchor = acc._alignment_date
        if anchor.tzinfo is None:
            anchor = anchor.astimezone()
    except Exception:
        return
    if anchor >= now - timedelta(hours=1):
        acc._alignment_date = now - timedelta(days=8)
        acc._alignment_index = 0
