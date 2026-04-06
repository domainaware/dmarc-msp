"""Client management API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dmarc_msp.api.dependencies import (
    ClientServiceDep,
    DashboardServiceDep,
    DbDep,
    OpenSearchServiceDep,
    RetentionServiceDep,
    SettingsDep,
)
from dmarc_msp.api.schemas import (
    ClientCreate,
    ClientOffboard,
    ClientRename,
    ClientUpdate,
)
from dmarc_msp.cli.helpers import get_offboarding_service
from dmarc_msp.models import ClientInfo
from dmarc_msp.services.clients import ClientAlreadyExistsError, ClientNotFoundError

router = APIRouter()


@router.post("", response_model=ClientInfo, status_code=201)
def create_client(
    body: ClientCreate,
    svc: ClientServiceDep,
    os_svc: OpenSearchServiceDep,
    dash_svc: DashboardServiceDep,
    ret_svc: RetentionServiceDep,
):
    # Verify OpenSearch is reachable before creating the client
    try:
        os_svc.health()
    except Exception as e:
        raise HTTPException(503, f"Cannot connect to OpenSearch: {e}")

    try:
        client = svc.create(
            name=body.name,
            contact_email=body.contact_email,
            index_prefix=body.index_prefix,
            notes=body.notes,
            retention_days=body.retention_days,
        )
        os_svc.provision_tenant(client.tenant_name, client.index_prefix)
        if client.retention_days:
            ret_svc.create_client_policy(client.index_prefix, client.retention_days)
        dash_svc.import_for_client(client.tenant_name, client.index_prefix)
        return svc.to_info(client)
    except ClientAlreadyExistsError as e:
        raise HTTPException(409, str(e))


@router.get("", response_model=list[ClientInfo])
def list_clients(svc: ClientServiceDep, include_offboarded: bool = False):
    clients = svc.list(include_offboarded=include_offboarded)
    return [svc.to_info(c) for c in clients]


@router.get("/{name}", response_model=ClientInfo)
def get_client(name: str, svc: ClientServiceDep):
    try:
        return svc.to_info(svc.get(name))
    except ClientNotFoundError as e:
        raise HTTPException(404, str(e))


@router.patch("/{name}", response_model=ClientInfo)
def update_client(name: str, body: ClientUpdate, svc: ClientServiceDep):
    try:
        kwargs = body.model_dump(exclude_none=True)
        client = svc.update(name, **kwargs)
        return svc.to_info(client)
    except ClientNotFoundError as e:
        raise HTTPException(404, str(e))


@router.post("/{name}/rename", response_model=ClientInfo)
def rename_client(name: str, body: ClientRename, svc: ClientServiceDep):
    try:
        client = svc.rename(name, body.new_name)
        return svc.to_info(client)
    except ClientNotFoundError as e:
        raise HTTPException(404, str(e))
    except ClientAlreadyExistsError as e:
        raise HTTPException(409, str(e))


@router.post("/{name}/offboard")
def offboard_client(name: str, body: ClientOffboard, settings: SettingsDep, db: DbDep):
    try:
        svc = get_offboarding_service(settings, db)
        result = svc.offboard_client(
            name, purge_dns=True, purge_indices=body.purge_indices
        )
        response = {
            "message": f"Offboarded {result.client_name}",
            "domains_removed": result.domains_removed,
        }
        if result.dns_failures:
            response["dns_failures"] = [
                {"domain": d, "error": e} for d, e in result.dns_failures
            ]
        return response
    except ClientNotFoundError as e:
        raise HTTPException(404, str(e))
