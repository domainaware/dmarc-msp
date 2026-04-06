"""Request/response schemas for the API."""

from __future__ import annotations

from pydantic import BaseModel


class ClientCreate(BaseModel):
    name: str
    contact_email: str | None = None
    index_prefix: str | None = None
    notes: str | None = None
    retention_days: int | None = None


class ClientUpdate(BaseModel):
    contact_email: str | None = None
    notes: str | None = None
    retention_days: int | None = None


class ClientRename(BaseModel):
    new_name: str


class DomainAdd(BaseModel):
    client_name: str
    domain: str
    create_client: bool = False


class DomainRemove(BaseModel):
    domain: str
    keep_dns: bool = False


class DomainMove(BaseModel):
    domain: str
    to_client: str


class CleanupDNSRequest(BaseModel):
    dry_run: bool = True


class ClientOffboard(BaseModel):
    purge_indices: bool = False


class TenantProvision(BaseModel):
    client_name: str


class DashboardImport(BaseModel):
    client_name: str


class DashboardDarkMode(BaseModel):
    client_name: str
    enabled: bool


class AnalystCreate(BaseModel):
    username: str


class ClientUserCreate(BaseModel):
    username: str


class UserCredentials(BaseModel):
    username: str
    password: str
    message: str


class UserInfo(BaseModel):
    username: str
    role_type: str
    client_tenant: str | None = None
    disabled: bool = False
    description: str = ""


class MessageResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    detail: str
