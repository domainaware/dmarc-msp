"""SQLAlchemy models and database session management."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from dmarc_msp.models import ClientStatus, DomainStatus


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ClientRow(Base):
    __tablename__ = "clients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    index_prefix: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    tenant_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(ClientStatus, values_callable=lambda x: [e.value for e in x]),
        default=ClientStatus.ACTIVE.value,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, onupdate=_utcnow
    )
    offboarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    domains: Mapped[list[DomainRow]] = relationship(
        "DomainRow", back_populates="client", lazy="selectin"
    )

    @property
    def active_domains(self) -> list[DomainRow]:
        return [
            d
            for d in self.domains
            if d.status not in (DomainStatus.OFFBOARDED.value, DomainStatus.OFFBOARDED)
        ]


class DomainRow(Base):
    __tablename__ = "domains"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clients.id"), nullable=False
    )
    domain_name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    dns_record_id: Mapped[str | None] = mapped_column(String, nullable=True)
    dns_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    dns_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        Enum(DomainStatus, values_callable=lambda x: [e.value for e in x]),
        default=DomainStatus.PENDING_DNS.value,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    offboarded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    client: Mapped[ClientRow] = relationship("ClientRow", back_populates="domains")


class AuditLogRow(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("clients.id"), nullable=True
    )
    domain: Mapped[str | None] = mapped_column(String, nullable=True)
    action: Mapped[str] = mapped_column(String, nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


def slugify(name: str) -> str:
    """Convert a client name to a slug suitable for index prefixes.

    Example: "Acme Corp" -> "acme_corp"
    """
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug


def init_db(database_url: str) -> sessionmaker[Session]:
    """Create engine and tables, return a sessionmaker."""
    engine = create_engine(database_url, echo=False)

    # Enable WAL mode and case-insensitive LIKE for SQLite
    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)
