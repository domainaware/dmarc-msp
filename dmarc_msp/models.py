"""Pydantic models and enums for dmarc-msp."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field


class ClientStatus(enum.StrEnum):
    ACTIVE = "active"
    OFFBOARDED = "offboarded"


class DomainStatus(enum.StrEnum):
    PENDING_DNS = "pending_dns"
    ACTIVE = "active"
    OFFBOARDING = "offboarding"
    OFFBOARDED = "offboarded"


class ClientInfo(BaseModel):
    """Read-only view of a client."""

    id: int
    name: str
    index_prefix: str
    tenant_name: str
    contact_email: str | None = None
    notes: str | None = None
    retention_days: int | None = None
    status: ClientStatus = ClientStatus.ACTIVE
    created_at: datetime
    updated_at: datetime | None = None
    offboarded_at: datetime | None = None
    domains: list[DomainInfo] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DomainInfo(BaseModel):
    """Read-only view of a domain."""

    id: int
    domain_name: str
    client_id: int
    dns_record_id: str | None = None
    dns_verified: bool = False
    dns_verified_at: datetime | None = None
    status: DomainStatus = DomainStatus.PENDING_DNS
    created_at: datetime
    offboarded_at: datetime | None = None

    model_config = {"from_attributes": True}


class OnboardingResult(BaseModel):
    client_name: str
    domain: str
    dns_verified: bool = False
    dns_record_existed: bool = False
    tenant: str
    index_prefix: str


class OffboardingResult(BaseModel):
    client_name: str
    domains_removed: int = 0


class DomainRemovalResult(BaseModel):
    domain: str
    client_name: str


class MoveResult(BaseModel):
    domain: str
    from_client: str
    to_client: str


class BulkResult(BaseModel):
    succeeded: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    failed: list[tuple[str, str]] = Field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.succeeded) + len(self.skipped) + len(self.failed)
