"""Vercel web app: login + map + read-only APIs. Imports NO Find My code.

This is what Vercel serves. It only reads positions from the shared database
(written by the GitHub Actions poller), so it has no native dependencies and
deploys within serverless limits. Admin here manages clients/users and views
trackers; adding trackers and polling happen off-Vercel (local script + Actions).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import (
    hash_password,
    make_session_cookie,
    read_session_cookie,
    verify_password,
)
from .db import Base, SessionLocal, engine, get_db
from .models import Client, Position, Tracker, User

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
    db = SessionLocal()
    try:
        if db.scalar(select(func.count()).select_from(User)) == 0:
            db.add(User(email="admin@local", password_hash=hash_password("admin"), role="team"))
            db.commit()
            log.warning("Seeded default admin: admin@local / admin — CHANGE THIS.")
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
    resp.set_cookie(COOKIE, make_session_cookie(user.id), httponly=True, samesite="lax")
    return resp


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
