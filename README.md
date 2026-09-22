# Tracker CRM

Self-hosted web app that shows your Find My tags on a map, for your team and
for clients — each client seeing only their own tags. Runs on Windows, no
iPhone needed to view. Data flow:

```
Kingtodo tag  ->  Apple Find My network  ->  fetcher (polls every 15 min,
                                              decrypts)  ->  MySQL  ->  web map
```

The tags are added by uploading the OpenTagViewer export .zip (the one you
already made). Keys are encrypted at rest; only the fetcher decrypts them in
memory to query Apple.

---

## What you need

- A Windows machine that stays on (server, office PC, or a VPS)
- Python 3.10–3.14 (from python.org — tick "Add to PATH" during install)
- MySQL 8 (local or hosted). SQLite works too for a quick trial (see below).
- The disposable Apple ID used only for fetching locations
- One OpenTagViewer export .zip per set of tags, plus its passcode

---

## Setup (once)

1. **Unzip this project** somewhere, e.g. `C:\tracker-crm`.

2. **Create the config file.** Copy `.env.example` to `.env` and fill it in:
   - `DB_URL` — your MySQL connection string. To trial without MySQL, use the
     SQLite line instead (commented in the file).
   - `SECRET_KEY` — any long random string.
   - `KEY_ENCRYPTION_KEY` — generate one:
     ```
     python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
     ```
     Paste the output as the value. **Back this up** — losing it means the
     stored tag keys can't be decrypted and every tag must be re-imported.

3. **Create the MySQL database** (skip if using SQLite):
   ```sql
   CREATE DATABASE tracker CHARACTER SET utf8mb4;
   CREATE USER 'tracker'@'localhost' IDENTIFIED BY 'your-password';
   GRANT ALL PRIVILEGES ON tracker.* TO 'tracker'@'localhost';
   ```
   Tables are created automatically on first run.

4. **Log in to Apple once** (needs the 2FA code, so it's interactive):
   ```
   setup-apple-login.bat
   ```
   Enter the disposable Apple ID, password, and the SMS/device code. The
   session is cached so the fetcher runs unattended afterwards.

   > If you hit an SSL "certificate verify failed" error, run
   > `Install Certificates.command` from your Python install once, or
   > `pip install --upgrade certifi`.

---

## Run

```
run.bat
```

Then open **http://localhost:8000** in a browser.

First login (created automatically):

```
email:    admin@local
password: admin
```

**Change this immediately** — create your real team users and delete or ignore
the default. (User management for team accounts is a small addition; for now
add team users directly, or ask and I'll add a "team users" admin section.)

---

## Using it

In **Admin** (top-right, team users only):

- **Add a client** — an organisation you serve. Tags and client-users attach to it.
- **Add a tracker** — upload the OpenTagViewer export .zip + its passcode, and
  optionally assign it to a client. Every tag in the zip is imported. A fetch
  runs immediately so it appears without waiting for the next cycle.
- **Add a client user** — an external login that sees only that client's tags.

The **Map** shows each visible tag with its last position, how long ago it was
seen, accuracy, and battery. It refreshes every minute. Positions only appear
once an iPhone has passed near the tag (the ~15+ min Find My delay applies).

---

## Deploying as a Windows service (always on)

`run.bat` runs in a console window. To run it in the background and restart on
reboot, use **NSSM** (https://nssm.cc):

```
nssm install TrackerCRM "C:\tracker-crm\.venv\Scripts\python.exe" "-m uvicorn app.main:app --host 0.0.0.0 --port 8000"
nssm set TrackerCRM AppDirectory C:\tracker-crm
nssm start TrackerCRM
```

Put it behind a reverse proxy (Caddy/nginx) with HTTPS if clients access it
over the internet.

---

## Project layout

```
app/
  config.py            settings from .env
  db.py                database engine/session
  models.py            Client, User, Tracker, Position tables
  security.py          password hashing, login cookie, key encryption
  tag_store.py         read export .zip -> Find My key objects
  apple_account.py     cached Apple session
  setup_apple_login.py one-time interactive login
  fetcher.py           poll Apple, decrypt, store positions
  main.py              web app: login, map, admin, API, scheduler
  templates/           login, map, admin pages
requirements.txt
.env.example
run.bat
setup-apple-login.bat
```

## API (for wiring into another CRM)

All require the login cookie; client users are auto-scoped to their tags.

- `GET /api/trackers` — each visible tag + its latest position
- `GET /api/trackers/{id}/history?limit=500` — position history for one tag

---

## Notes and limits

- **Delay is inherent.** Find My reports are batched; expect 15+ min old data.
  Positions exist only where an iPhone passed the tag. No foot traffic = no fix.
- **Unofficial route.** Fetching uses a reverse-engineered path; the Apple ID
  can be flagged. Keep it disposable and separate from anything important.
- **GDPR.** If tags go on items people carry, this is personal-data tracking.
  Clients need a lawful basis and must inform those people. Cover it in the
  service contract.
- **Back up `KEY_ENCRYPTION_KEY` and `.env`.** Without the key, stored tag keys
  are unrecoverable.
```
