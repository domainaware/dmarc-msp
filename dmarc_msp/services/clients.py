"""Client CRUD service."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from dmarc_msp.db import AuditLogRow, ClientRow, slugify
from dmarc_msp.models import ClientInfo, ClientStatus

logger = logging.getLogger(__name__)


class ClientNotFoundError(Exception):
    pass


class ClientAlreadyExistsError(Exception):
    pass


class ClientService:
    def __init__(self, db: Session):
        self.db = db

    def create(
        self,
        name: str,
        contact_email: str | None = None,
        index_prefix: str | None = None,
        notes: str | None = None,
        retention_days: int | None = None,
    ) -> ClientRow:
        """Create a new client."""
        name_lower = name.lower().strip()
        slug = slugify(name)
        index_prefix = (index_prefix or slug).lower().strip()
        tenant_name = slug

        existing = (
            self.db.query(ClientRow).filter(ClientRow.name == name_lower).first()
        )
        if existing:
            if existing.status == ClientStatus.OFFBOARDED.value:
                # Reactivate
                existing.status = ClientStatus.ACTIVE.value
                existing.offboarded_at = None
                existing.contact_email = contact_email or existing.contact_email
                existing.notes = notes or existing.notes
                existing.retention_days = (
                    retention_days
                    if retention_days is not None
                    else existing.retention_days
                )
                self.db.commit()
                self.db.refresh(existing)
                logger.info("Reactivated client: %s", name_lower)
                return existing
            raise ClientAlreadyExistsError(f"Client '{name}' already exists")

        client = ClientRow(
            name=name_lower,
            index_prefix=index_prefix,
            tenant_name=tenant_name,
            contact_email=contact_email,
            notes=notes,
            retention_days=retention_days,
        )
        self.db.add(client)
        self._audit("client_create", client_row=client)
        self.db.commit()
        self.db.refresh(client)
        logger.info("Created client: %s (prefix=%s)", name_lower, index_prefix)
        return client

    def get(self, name: str) -> ClientRow:
        """Get a client by name."""
        client = (
            self.db.query(ClientRow)
            .filter(ClientRow.name == name.lower().strip())
            .first()
        )
        if not client:
            raise ClientNotFoundError(f"Client '{name}' not found")
        return client

    def get_by_id(self, client_id: int) -> ClientRow:
        client = self.db.query(ClientRow).filter(ClientRow.id == client_id).first()
        if not client:
            raise ClientNotFoundError(f"Client with id {client_id} not found")
        return client

    def list(self, include_offboarded: bool = False) -> list[ClientRow]:
        """List all clients."""
        query = self.db.query(ClientRow)
        if not include_offboarded:
            query = query.filter(ClientRow.status != ClientStatus.OFFBOARDED.value)
        return query.order_by(ClientRow.name).all()

    def update(self, name: str, **kwargs) -> ClientRow:
        """Update mutable fields: contact_email, notes, retention_days."""
        client = self.get(name)
        allowed = {"contact_email", "notes", "retention_days"}
        for key, value in kwargs.items():
            if key in allowed and value is not None:
                setattr(client, key, value)
        self._audit("client_update", client_row=client, detail=kwargs)
        self.db.commit()
        self.db.refresh(client)
        return client

    def rename(self, current_name: str, new_name: str) -> ClientRow:
        """Rename a client. Index prefix and tenant name stay the same."""
        client = self.get(current_name)
        new_name_lower = new_name.lower().strip()

        # Check the new name isn't already taken
        existing = (
            self.db.query(ClientRow)
            .filter(ClientRow.name == new_name_lower)
            .first()
        )
        if existing and existing.id != client.id:
            raise ClientAlreadyExistsError(
                f"Client '{new_name}' already exists"
            )

        old_name = client.name
        client.name = new_name_lower
        self._audit(
            "client_rename",
            client_row=client,
            detail={"old_name": old_name, "new_name": new_name_lower},
        )
        self.db.commit()
        self.db.refresh(client)
        logger.info(
            "Renamed client: %s -> %s (prefix=%s unchanged)",
            old_name,
            new_name_lower,
            client.index_prefix,
        )
        return client

    def to_info(self, client: ClientRow) -> ClientInfo:
        """Convert a DB row to a Pydantic model."""
        return ClientInfo.model_validate(client)

    def _audit(
        self,
        action: str,
        client_row: ClientRow | None = None,
        domain: str | None = None,
        detail: dict | None = None,
        success: bool = True,
    ):
        log = AuditLogRow(
            client_id=client_row.id if client_row and client_row.id else None,
            domain=domain,
            action=action,
            detail=detail,
            success=success,
        )
        self.db.add(log)
