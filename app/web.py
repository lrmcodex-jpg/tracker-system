"""Vercel web app: login + map + read-only APIs. Imports NO Find My code.

This is what Vercel serves. It only reads positions from the shared database
(written by the GitHub Actions poller), so it has no native dependencies and
deploys within serverless limits. Admin here manages clients/users and views
trackers; adding trackers and polling happen off-Vercel (local script + Actions).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import (
    SESSION_MAX_AGE,
    hash_password,
    make_session_cookie,
    read_session_cookie,
    verify_password,
)
from .config import SERVERLESS
from .db import Base, SessionLocal, engine, get_db
from .models import Client, Position, Tracker, User

# Only a local plain-HTTP run may send the cookie without the Secure flag.
# Vercel is always HTTPS, so there Secure is always on.
LOCAL_HTTP = not SERVERLESS and os.environ.get("ALLOW_INSECURE_COOKIE") == "1"

log = logging.getLogger("web")
logging.basicConfig(level=logging.INFO)

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="Tracker Map")
_static = BASE / "static"
if _static.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")

COOKIE = "session"


@app.on_event("startup")
def startup() -> None:
    # Safe to call repeatedly; creates tables if the DB is fresh.
    Base.metadata.create_all(engine)
    _seed_admin()


def _seed_admin() -> None:
    """Create the first team user from the environment, never from a default.

    A hardcoded admin@local/admin was previously seeded here. On a public URL that
    is a full compromise: the team role bypasses the per-client filter, so anyone
    who guessed it could read every tenant's live position and movement history.
    There is no default any more. If ADMIN_EMAIL/ADMIN_PASSWORD are absent we seed
    nothing and say so, which is safe: an empty user table locks everyone out
    rather than letting everyone in.
    """
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")

    db = SessionLocal()
    try:
        if db.scalar(select(func.count()).select_from(User)) != 0:
            return
        if not email or not password:
            log.warning(
                "No users exist and ADMIN_EMAIL/ADMIN_PASSWORD are not set, so no "
                "account was created. Set both in the environment and redeploy."
            )
            return
        db.add(User(email=email, password_hash=hash_password(password), role="team"))
        db.commit()
        log.info("Seeded first team user %s from the environment.", email)
    finally:
        db.close()


# --- auth helpers -----------------------------------------------------------
class _Redirect(Exception):
    def __init__(self, to: str):
        self.to = to


@app.exception_handler(_Redirect)
async def _redirect_handler(request: Request, exc: _Redirect):
    return RedirectResponse(exc.to, status_code=302)


def current_user(request: Request, db: Session) -> User | None:
    uid = read_session_cookie(request.cookies.get(COOKIE))
    return db.get(User, uid) if uid is not None else None


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    u = current_user(request, db)
    if u is None:
        raise _Redirect("/login")
    return u


def require_team(request: Request, db: Session = Depends(get_db)) -> User:
    u = require_user(request, db)
    if not u.is_team:
        raise _Redirect("/")
    return u


# --- login / logout ---------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(request, "login.html", {"error": "Wrong email or password."})
    resp = RedirectResponse("/", status_code=302)
    _set_session(resp, user.id)
    return resp


def _set_session(resp, user_id: int) -> None:
    """Attach the login cookie. Secure off only for a plain-HTTP local run."""
    resp.set_cookie(
        COOKIE,
        make_session_cookie(user_id),
        httponly=True,
        samesite="lax",
        secure=not LOCAL_HTTP,
        max_age=SESSION_MAX_AGE,
    )


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(COOKIE)
    return resp


# --- map --------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def map_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse(request, "map.html", {"user": user})


def _visible(db: Session, user: User):
    stmt = select(Tracker).where(Tracker.active == 1)
    if not user.is_team:
        stmt = stmt.where(Tracker.client_id == user.client_id)
    return list(db.scalars(stmt).all())


@app.get("/api/trackers")
def api_trackers(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    out = []
    for t in _visible(db, user):
        latest = db.scalar(
            select(Position).where(Position.tracker_id == t.id)
            .order_by(Position.reported_at.desc()).limit(1)
        )
        row = {"id": t.id, "name": t.name, "latitude": None}
        if latest:
            row.update(latitude=latest.latitude, longitude=latest.longitude,
                       accuracy_m=latest.accuracy_m, battery=latest.battery,
                       reported_at=latest.reported_at.isoformat())
        out.append(row)
    return out


@app.get("/api/trackers/{tracker_id}/history")
def api_history(tracker_id: int, request: Request, db: Session = Depends(get_db), limit: int = 500):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    t = db.get(Tracker, tracker_id)
    if t is None or (not user.is_team and t.client_id != user.client_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    rows = db.scalars(
        select(Position).where(Position.tracker_id == tracker_id)
        .order_by(Position.reported_at.desc()).limit(limit)
    ).all()
    return [{"latitude": p.latitude, "longitude": p.longitude,
             "accuracy_m": p.accuracy_m, "reported_at": p.reported_at.isoformat()} for p in rows]


# --- admin (DB-only management; no tracker import / no polling here) ---------
def _admin_ctx(request, db, user, msg=None, kind="ok"):
    clients = list(db.scalars(select(Client).order_by(Client.name)).all())
    trackers = list(db.scalars(select(Tracker).order_by(Tracker.name)).all())
    for t in trackers:
        t.pos_count = db.scalar(select(func.count()).select_from(Position).where(Position.tracker_id == t.id))
    return {"request": request, "user": user, "clients": clients, "trackers": trackers,
            "msg": msg, "msg_kind": kind, "can_add_tracker": False}


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, user: User = Depends(require_team), db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "admin.html", _admin_ctx(request, db, user))


@app.post("/admin/add-client")
def add_client(request: Request, name: str = Form(...),
               user: User = Depends(require_team), db: Session = Depends(get_db)):
    db.add(Client(name=name.strip())); db.commit()
    return templates.TemplateResponse(request, "admin.html", _admin_ctx(request, db, user, f"Client '{name}' added."))


@app.post("/admin/add-user")
def add_user(request: Request, email: str = Form(...), password: str = Form(...),
             client_id: int = Form(...), user: User = Depends(require_team),
             db: Session = Depends(get_db)):
    email = email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        return templates.TemplateResponse(request, "admin.html",
            _admin_ctx(request, db, user, "That email already exists.", "err"))
    db.add(User(email=email, password_hash=hash_password(password), role="client", client_id=client_id))
    db.commit()
    return templates.TemplateResponse(request, "admin.html",
        _admin_ctx(request, db, user, f"Client user '{email}' created."))


@app.post("/admin/add-team-user")
def add_team_user(request: Request, email: str = Form(...), password: str = Form(...),
                  user: User = Depends(require_team), db: Session = Depends(get_db)):
    email = email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        return templates.TemplateResponse(request, "admin.html",
            _admin_ctx(request, db, user, "That email already exists.", "err"))
    db.add(User(email=email, password_hash=hash_password(password), role="team", client_id=None))
    db.commit()
    return templates.TemplateResponse(request, "admin.html",
        _admin_ctx(request, db, user, f"Team user '{email}' created (full access)."))


# --- account: change your own password --------------------------------------
# This did not exist before. Without it the only team account was whatever got
# seeded at first boot, with no way to rotate its password from the app.
_ACCOUNT_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>Change password</title><meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;
display:flex;min-height:100vh;align-items:center;justify-content:center;margin:0}
form{background:#1e293b;padding:2rem;border-radius:12px;width:min(92vw,360px)}
h1{font-size:1.1rem;margin:0 0 1rem}label{display:block;font-size:.8rem;margin:.75rem 0 .25rem;color:#94a3b8}
input{width:100%;padding:.55rem;border-radius:6px;border:1px solid #334155;background:#0f172a;color:#e2e8f0;box-sizing:border-box}
button{margin-top:1.25rem;width:100%;padding:.6rem;border:0;border-radius:6px;background:#3b82f6;color:#fff;font-size:.9rem;cursor:pointer}
.msg{margin-top:1rem;font-size:.85rem}.err{color:#f87171}.ok{color:#4ade80}
a{color:#94a3b8;font-size:.8rem;display:inline-block;margin-top:1rem}</style></head>
<body><form method="post" action="/account/password">
<h1>Change password &mdash; __EMAIL__</h1>
<label>Current password</label><input type="password" name="current" required>
<label>New password (min 12 characters)</label><input type="password" name="new1" required>
<label>Repeat new password</label><input type="password" name="new2" required>
<button type="submit">Change password</button>
<div class="msg __CLS__">__MSG__</div><a href="/">&larr; Back to map</a>
</form></body></html>"""


def _account_page(user: User, msg: str = "", cls: str = "") -> HTMLResponse:
    html = (_ACCOUNT_PAGE.replace("__EMAIL__", user.email)
            .replace("__MSG__", msg).replace("__CLS__", cls))
    return HTMLResponse(html)


@app.get("/account", response_class=HTMLResponse)
def account_page(request: Request, user: User = Depends(require_user)):
    return _account_page(user)


@app.post("/account/password")
def change_password(request: Request, current: str = Form(...), new1: str = Form(...),
                    new2: str = Form(...), user: User = Depends(require_user),
                    db: Session = Depends(get_db)):
    if not verify_password(current, user.password_hash):
        return _account_page(user, "Current password is wrong.", "err")
    if new1 != new2:
        return _account_page(user, "The two new passwords do not match.", "err")
    if len(new1) < 12:
        return _account_page(user, "New password must be at least 12 characters.", "err")
    if new1 == current:
        return _account_page(user, "New password must differ from the current one.", "err")

    user.password_hash = hash_password(new1)
    db.commit()
    log.info("Password changed for %s", user.email)

    # Re-issue the cookie so the current browser stays logged in.
    resp = RedirectResponse("/", status_code=302)
    _set_session(resp, user.id)
    return resp


# --- refresh ----------------------------------------------------------------
# The map has a "Refresh now" button that POSTs here. This endpoint existed only
# in app/main.py (the local app), so on Vercel it 404'd and the button always
# said "Failed".
#
# Vercel cannot poll Apple itself: the Find My stack needs native libraries that
# are deliberately excluded from this bundle. So the honest implementation is to
# ask GitHub Actions to run the poller, which is where the fetching actually
# lives. Needs GH_DISPATCH_TOKEN (fine-grained PAT, Actions: read+write on this
# repo). Without it we say so plainly instead of failing.
GH_REPO = os.environ.get("GH_REPO", "lrmcodex-jpg/tracker-system")
GH_WORKFLOW = os.environ.get("GH_WORKFLOW", "poll.yml")


@app.post("/api/refresh")
def api_refresh(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    newest = db.scalar(select(func.max(Position.reported_at)))
    newest_iso = newest.isoformat() if newest else None

    token = os.environ.get("GH_DISPATCH_TOKEN", "")
    if not token:
        return JSONResponse({
            "ok": False,
            "reason": "not_configured",
            "message": ("Polling runs on GitHub Actions, not on this site. "
                        "Set GH_DISPATCH_TOKEN to enable this button."),
            "newest": newest_iso,
        }, status_code=200)

    import json as _json
    import urllib.error
    import urllib.request

    url = f"https://api.github.com/repos/{GH_REPO}/actions/workflows/{GH_WORKFLOW}/dispatches"
    req = urllib.request.Request(
        url,
        data=_json.dumps({"ref": "main"}).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "tracker-system",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = resp.status in (201, 204)
    except urllib.error.HTTPError as e:
        log.error("Workflow dispatch failed: %s %s", e.code, e.reason)
        return JSONResponse({"ok": False, "reason": "dispatch_failed",
                             "message": f"GitHub refused the request ({e.code}).",
                             "newest": newest_iso}, status_code=200)
    except Exception as e:  # noqa: BLE001
        log.error("Workflow dispatch error: %s", e)
        return JSONResponse({"ok": False, "reason": "dispatch_error",
                             "message": "Could not reach GitHub.",
                             "newest": newest_iso}, status_code=200)

    # The poller takes ~40s. The page keeps re-reading the database on its timer,
    # so a new position appears on its own shortly after.
    return {"ok": ok, "started": True,
            "message": "Poller started. New positions appear within about a minute.",
            "newest": newest_iso}
