# Deploying: Vercel (website) + GitHub Actions (poller) + cloud MySQL

The Find My fetching runs on **GitHub Actions** (a real Linux machine on a
schedule). The **website** runs on **Vercel** and only reads the database. They
share one **cloud MySQL**. Nothing needs to stay on your Mac.

```
GitHub Actions (cron 5 min)  →  fetch + decrypt  →  ┐
                                                     ├→  cloud MySQL  →  Vercel website  →  visitors
local: setup login / add tags  ────────────────────┘
```

## 1. Cloud MySQL
Create a free MySQL (PlanetScale, Aiven, or Railway). Get its connection string:
```
mysql+pymysql://USER:PASSWORD@HOST:PORT/DBNAME
```
Keep it — it's the `DB_URL` used everywhere below.

## 2. Secrets you need
- `DB_URL` — the MySQL string above
- `KEY_ENCRYPTION_KEY` — your existing Fernet key (MUST match what tags were imported with)
- `SECRET_KEY` — any long random string (signs the login cookie)

## 3. One-time login + import (locally, pointed at the cloud DB)
On your Mac, set `.env` `DB_URL` to the cloud MySQL, then:
```
python -m app.setup_apple_login          # stores the Apple session IN the cloud DB
python -m app.add_tracker <export.zip>   # imports your tag(s) into the cloud DB
```
(Do these against the cloud DB so Actions and Vercel see them.)

## 4. GitHub Actions (poller)
In your repo: Settings → Secrets and variables → Actions → add `DB_URL`,
`KEY_ENCRYPTION_KEY`, `SECRET_KEY`. The workflow `.github/workflows/poll.yml`
runs every 5 minutes automatically; you can also run it manually from the
Actions tab. Watch its logs to confirm "Stored N new position(s)".

## 5. Vercel (website)
Import the GitHub repo at vercel.com. Framework preset: **Other**. Vercel uses
`vercel.json` + `api/index.py` automatically, installing only the slim
`requirements.txt` (no Find My libs). Add the same env vars (`DB_URL`,
`SECRET_KEY`; `KEY_ENCRYPTION_KEY` not needed by the site but harmless) in
Vercel → Settings → Environment Variables. Deploy. Your site is the Vercel URL.

Log in with the seeded `admin@local` / `admin` and change it.

## Notes
- Poll interval is 5 min (Actions cron minimum). Find My is delayed anyway.
- Adding a tag or first login is always local (needs Find My libs + 2FA).
- The website never runs Find My code, so it deploys within Vercel's limits.
- Keep the repo PRIVATE. Secrets live in GitHub/Vercel settings, never in git.
