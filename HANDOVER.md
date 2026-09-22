# Tracker System — Handover

This is what a new person needs to run and maintain the system without the
original setup person. Read this first.

## What the system is

A website that shows Find My tags on a map. Team users see all tags; each
client user sees only their own. Locations come from Apple's Find My network,
fetched every 5 minutes by an automated job, stored in a cloud database, and
displayed by a website.

```
GitHub Actions (poller, every 5 min)  -->  Supabase (database)  -->  Vercel (website)  -->  users
        ^                                                                  
   local machine: add trackers, re-login to Apple when needed
```

## The three services (get access to all three)

- **GitHub** — code + the poller. Repo: `lrmcodex-jpg/tracker-system`.
  Add people via repo Settings -> Collaborators.
- **Supabase** — the database. Add people via Supabase -> project -> Settings -> Team.
- **Vercel** — the website. Add people via Vercel -> project -> Settings -> Members.

## The secrets (store in a password manager, NOT in chat or git)

- `DB_URL` — Supabase connection string.
- `KEY_ENCRYPTION_KEY` — encrypts the tag keys. **If lost, every tracker must be
  re-imported.** Back it up in two places.
- `SECRET_KEY` — signs the login cookie.
- Shared **Apple ID** email + password, and access to its **2FA phone number**.
- GitHub token (or each dev uses their own GitHub login).

These live in three places and must match: your local `.env`, the GitHub repo
Secrets (Settings -> Secrets and variables -> Actions), and Vercel env vars.

## THE ONE RULE: one shared Apple ID

The whole system fetches through a SINGLE Apple ID, stored once in the database.

- Tags MUST be paired on an iPhone/iPad signed into THIS shared Apple ID.
  A tag paired on someone's personal Apple ID cannot be fetched by the system.
- The 2FA code goes to this Apple ID's phone number. Whoever re-logs in needs
  that code. Set the trusted number to a phone the team controls.

## Website admin (no code needed — just the browser)

Log in as a team user, click **Admin**:
- **Add a client** — an organisation you serve.
- **Add a client user** — a login that sees only that client's tags.
- **Add a team user** — a login with full access (all tags + admin).
- Trackers are added from the command line (see below), then assigned to a
  client here.

First login (change immediately): `admin@local` / `admin`.

## Local machine setup (needed to add trackers / re-login to Apple)

Adding a tracker and re-logging in to Apple need the Find My libraries, which
don't run on the website host. So one team member keeps the repo cloned locally:

```
git clone https://github.com/lrmcodex-jpg/tracker-system.git
cd tracker-system
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-poller.txt
cp .env.example .env                 # then fill in DB_URL, SECRET_KEY, KEY_ENCRYPTION_KEY
```

Point `.env`'s `DB_URL` at the same Supabase database.

## Runbook: add a new tracker

1. Turn on the tag (pull the battery tab / press the button — it beeps).
2. On the iPhone signed into the SHARED Apple ID: Find My -> Items -> + ->
   Add Other Item -> pair it -> name it.
3. Export it with the OpenTagViewer AirTag Exporter -> get the .zip + passcode.
4. On the local machine:
   ```
   python -m app.add_tracker /path/to/export.zip
   ```
   Enter the passcode when asked.
5. In the website Admin, assign the new tracker to the right client.
6. Wait for the next poll (up to ~5 min) — it appears on the map once an iPhone
   has passed near the tag.

## Runbook: the map went stale / poller failing

The poller opens a GitHub issue labelled `poller-alert` when it fails (GitHub
emails repo watchers). Most often the Apple session expired. Fix:

```
cd tracker-system
source .venv/bin/activate
python -m app.setup_apple_login
```

Enter the shared Apple ID + the 2FA code. It saves a fresh session to the
database; the next poll goes green. Close the alert issue.

## Changing the fetching Apple ID later

Possible any time, but each tag's keys are tied to the account that paired it,
so switching accounts means re-pairing and re-importing the existing tags:
1. Pair the tags on the new Apple ID's iPhone.
2. `python -m app.setup_apple_login` with the new account (overwrites the session).
3. `python -m app.add_tracker` for each tag again.
If you only need the 2FA code to go to a different phone, just change the
trusted number on the existing Apple ID — no re-import needed.

## Known limits (not bugs)

- **Delay:** Find My data is 15+ minutes old by nature; a stationary tag near
  few phones updates rarely. No code fixes this — it's how Find My works. For
  reliable live tracking, use GPS/LTE trackers instead.
- **Unofficial access:** fetching uses a reverse-engineered path; the Apple ID
  can be flagged or logged out by Apple. That's when a re-login is needed.
- **GDPR:** if tags go on items people carry, this is personal-data tracking.
  Clients need a lawful basis and must inform those people.

## Where the important files are

- `app/` — the application code
- `.github/workflows/poll.yml` — the 5-minute poller + failure alert
- `DEPLOY.md` — how the three services were set up
- `README.md` — local run instructions
