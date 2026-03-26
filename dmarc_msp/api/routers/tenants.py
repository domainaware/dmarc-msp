"""Tenant provisioning API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dmarc_msp.api.dependencies import ClientServiceDep, OpenSearchServiceDep
from dmarc_msp.api.schemas import TenantProvision
from dmarc_msp.services.clients import ClientNotFoundError

router = APIRouter()


@router.post("/provision")
def provision_tenant(
    body: TenantProvision,
    client_svc: ClientServiceDep,
    os_svc: OpenSearchServiceDep,
):
    try:
        client = client_svc.get(body.client_name)
        os_svc.provision_tenant(client.tenant_name, client.index_prefix)
        return {"message": f"Provisioned tenant: {client.tenant_name}"}
    except ClientNotFoundError as e:
        raise HTTPException(404, str(e))


@router.post("/deprovision")
def deprovision_tenant(
    body: TenantProvision,
    client_svc: ClientServiceDep,
    os_svc: OpenSearchServiceDep,
):
    try:
        client = client_svc.get(body.client_name)
        os_svc.deprovision_tenant(client.tenant_name)
        return {"message": f"Deprovisioned tenant: {client.tenant_name}"}
    except ClientNotFoundError as e:
        raise HTTPException(404, str(e))
