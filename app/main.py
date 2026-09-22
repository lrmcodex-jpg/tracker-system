"""FastAPI app: login, role-based map, admin, and the fetcher schedule."""

from __future__ import annotations

import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import fetcher
from .config import POLL_INTERVAL_MIN
from .db import Base, SessionLocal, engine, get_db
from .models import Client, Position, Tracker, User
from .security import (
    decrypt_keys,  # noqa: F401  (kept for admin key checks if needed)
    encrypt_keys,
    hash_password,
    make_session_cookie,
    read_session_cookie,
    verify_password,
)
from .tag_store import load_accessories

log = logging.getLogger("app")
logging.basicConfig(level=logging.INFO)

BASE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

app = FastAPI(title="Tracker CRM")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

COOKIE = "session"


# --- Startup: create tables, seed first admin, start scheduler --------------
@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(engine)
    _seed_admin()
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        _safe_fetch, "interval", minutes=POLL_INTERVAL_MIN, next_run_time=None
    )
    scheduler.start()
    log.info("Scheduler started: polling every %d min.", POLL_INTERVAL_MIN)


def _safe_fetch() -> None:
    try:
        fetcher.run_once()
    except Exception as e:  # noqa: BLE001
        log.error("Scheduled fetch failed: %s", e)


def _seed_admin() -> None:
    """Create a default team admin on first run if there are no users."""
    db = SessionLocal()
    try:
        if db.scalar(select(func.count()).select_from(User)) == 0:
            admin = User(
                email="admin@local",
                password_hash=hash_password("admin"),
                role="team",
            )
            db.add(admin)
            db.commit()
            log.warning("Seeded default admin: admin@local / admin  — CHANGE THIS.")
    finally:
        db.close()


# --- Auth helpers -----------------------------------------------------------
def current_user(request: Request, db: Session) -> User | None:
    uid = read_session_cookie(request.cookies.get(COOKIE))
    if uid is None:
        return None
    return db.get(User, uid)


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = current_user(request, db)
    if user is None:
        raise _Redirect("/login")
    return user


def require_team(request: Request, db: Session = Depends(get_db)) -> User:
    user = require_user(request, db)
    if not user.is_team:
        raise _Redirect("/")
    return user


class _Redirect(Exception):
    def __init__(self, to: str):
        self.to = to


@app.exception_handler(_Redirect)
async def _redirect_handler(request: Request, exc: _Redirect):
    return RedirectResponse(exc.to, status_code=302)


# --- Login / logout ---------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
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


# --- Map --------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def map_page(request: Request, user: User = Depends(require_user)):
    return templates.TemplateResponse(request, "map.html", {"user": user})


def _visible_trackers(db: Session, user: User) -> list[Tracker]:
    stmt = select(Tracker).where(Tracker.active == 1)
    if not user.is_team:
        # Client users see only their own client's tags.
        stmt = stmt.where(Tracker.client_id == user.client_id)
    return list(db.scalars(stmt).all())


@app.post("/api/refresh")
def api_refresh(request: Request, db: Session = Depends(get_db)):
    """Force an immediate poll of Apple for the newest reports.

    This does NOT contact the tags (impossible over the internet). It fetches
    the latest reports other iPhones have already uploaded to Apple, without
    waiting for the 15-minute scheduler. Any logged-in user may trigger it;
    it refreshes every tracker, but each user still only SEES their own.
    """
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        result = fetcher.run_once()
    except Exception as e:  # noqa: BLE001
        log.error("Manual refresh failed: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"ok": True, "new_positions": result.get("new_positions", 0)}


@app.get("/api/trackers")
def api_trackers(request: Request, db: Session = Depends(get_db)):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    result = []
    for t in _visible_trackers(db, user):
        latest = db.scalar(
            select(Position)
            .where(Position.tracker_id == t.id)
            .order_by(Position.reported_at.desc())
            .limit(1)
        )
        row = {"id": t.id, "name": t.name, "latitude": None}
        if latest:
            row.update(
                latitude=latest.latitude,
                longitude=latest.longitude,
                accuracy_m=latest.accuracy_m,
                battery=latest.battery,
                reported_at=latest.reported_at.isoformat(),
            )
        result.append(row)
    return result


@app.get("/api/trackers/{tracker_id}/history")
def api_history(tracker_id: int, request: Request, db: Session = Depends(get_db), limit: int = 500):
    user = current_user(request, db)
    if user is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    t = db.get(Tracker, tracker_id)
    if t is None or (not user.is_team and t.client_id != user.client_id):
        return JSONResponse({"error": "not found"}, status_code=404)
    rows = db.scalars(
        select(Position)
        .where(Position.tracker_id == tracker_id)
        .order_by(Position.reported_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "latitude": p.latitude,
            "longitude": p.longitude,
            "accuracy_m": p.accuracy_m,
            "reported_at": p.reported_at.isoformat(),
        }
        for p in rows
    ]


# --- Admin ------------------------------------------------------------------
def _admin_ctx(request: Request, db: Session, user: User, msg=None, kind="ok"):
    clients = list(db.scalars(select(Client).order_by(Client.name)).all())
    trackers = list(db.scalars(select(Tracker).order_by(Tracker.name)).all())
    for t in trackers:
        t.pos_count = db.scalar(
            select(func.count()).select_from(Position).where(Position.tracker_id == t.id)
        )
    return {
        "request": request, "user": user, "clients": clients, "trackers": trackers,
        "msg": msg, "msg_kind": kind, "can_add_tracker": True,
    }


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, user: User = Depends(require_team), db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "admin.html", _admin_ctx(request, db, user))


@app.post("/admin/add-client")
def add_client(request: Request, name: str = Form(...),
               user: User = Depends(require_team), db: Session = Depends(get_db)):
    db.add(Client(name=name.strip()))
    db.commit()
    return templates.TemplateResponse(request, "admin.html", _admin_ctx(request, db, user, f"Client '{name}' added."))


@app.post("/admin/add-user")
def add_user(request: Request, email: str = Form(...), password: str = Form(...),
             client_id: int = Form(...), user: User = Depends(require_team),
             db: Session = Depends(get_db)):
    email = email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        return templates.TemplateResponse(request, "admin.html", _admin_ctx(request, db, user, "That email already exists.", "err"))
    db.add(User(email=email, password_hash=hash_password(password),
                role="client", client_id=client_id))
    db.commit()
    return templates.TemplateResponse(request, "admin.html", _admin_ctx(request, db, user, f"Client user '{email}' created."))


@app.post("/admin/add-tracker")
async def add_tracker(request: Request, export: UploadFile = File(...),
                      passcode: str = Form(...), client_id: str = Form(""),
                      user: User = Depends(require_team), db: Session = Depends(get_db)):
    data = await export.read()
    try:
        accessories = load_accessories(data, passcode)
    except Exception as e:  # noqa: BLE001
        return templates.TemplateResponse(request, "admin.html", _admin_ctx(request, db, user, f"Import failed: {e}", "err"))

    cid = int(client_id) if client_id else None
    added, skipped = 0, 0
    for identifier, name, keys_json in accessories:
        if db.scalar(select(Tracker).where(Tracker.identifier == identifier)):
            skipped += 1
            continue
        db.add(Tracker(
            name=name, identifier=identifier, client_id=cid,
            active=1, encrypted_keys=encrypt_keys(keys_json),
        ))
        added += 1
    db.commit()

    # Kick off an immediate fetch so the new tag shows up without waiting.
    try:
        fetcher.run_once()
    except Exception as e:  # noqa: BLE001
        log.error("Post-import fetch failed: %s", e)

    msg = f"Imported {added} tracker(s)." + (f" Skipped {skipped} already present." if skipped else "")
    return templates.TemplateResponse(request, "admin.html", _admin_ctx(request, db, user, msg))
