"""Database tables.

Design:
- Client      : an organisation you serve (a tenant). Tags belong to a client.
- User        : a login. Either staff (role='team', sees everything) or a
                client user (role='client', sees only their own client's tags).
- Tracker     : one physical tag. Holds its encrypted Find My keys as JSON.
- Position    : one decrypted location report for a tracker (history table).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Client(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    users: Mapped[list["User"]] = relationship(back_populates="client")
    trackers: Mapped[list["Tracker"]] = relationship(back_populates="client")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'team'  = your staff, sees all tags and admin screens
    # 'client'= external user, sees only their client's tags
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="client")
    # For client users: which client they belong to. NULL for team users.
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    client: Mapped["Client | None"] = relationship(back_populates="users")

    @property
    def is_team(self) -> bool:
        return self.role == "team"


class Tracker(Base):
    __tablename__ = "trackers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Human label shown on the map (e.g. "Van 1", "Asset A"). Keep it neutral.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # The tag's identifier from the export (UUID). Unique per tag.
    identifier: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id"), nullable=True)
    active: Mapped[bool] = mapped_column(Integer, default=1)
    # The Find My key material, serialized by FindMyAccessory.to_json and then
    # ENCRYPTED with Fernet. Never stored in plaintext.
    encrypted_keys: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    client: Mapped["Client | None"] = relationship(back_populates="trackers")
    positions: Mapped[list["Position"]] = relationship(
        back_populates="tracker", cascade="all, delete-orphan"
    )


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        # A tag can't have two reports for the exact same instant; keeps the
        # poller from inserting duplicates.
        UniqueConstraint("tracker_id", "reported_at", name="uq_tracker_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tracker_id: Mapped[int] = mapped_column(ForeignKey("trackers.id"), nullable=False, index=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy_m: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    battery: Mapped[str] = mapped_column(String(20), nullable=False, default="Unknown")
    # When Apple's network observed the tag (the real event time).
    reported_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # When our poller stored it.
    received_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    tracker: Mapped["Tracker"] = relationship(back_populates="positions")
