"""Dashboard import API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dmarc_msp.api.dependencies import ClientServiceDep, DashboardServiceDep
from dmarc_msp.api.schemas import DashboardDarkMode, DashboardImport
from dmarc_msp.services.clients import ClientNotFoundError

router = APIRouter()


@router.post("/import")
def import_dashboards(
    body: DashboardImport,
    client_svc: ClientServiceDep,
    dash_svc: DashboardServiceDep,
):
    try:
        client = client_svc.get(body.client_name)
        dash_svc.import_for_client(client.tenant_name, client.index_prefix)
        return {"message": f"Imported dashboards for {client.name}"}
    except ClientNotFoundError as e:
        raise HTTPException(404, str(e))
    except FileNotFoundError as e:
        raise HTTPException(500, str(e))


@router.post("/dark-mode")
def set_dark_mode(
    body: DashboardDarkMode,
    client_svc: ClientServiceDep,
    dash_svc: DashboardServiceDep,
):
    try:
        client = client_svc.get(body.client_name)
        dash_svc.set_dark_mode(client.tenant_name, body.enabled)
        state = "enabled" if body.enabled else "disabled"
        return {"message": f"Dark mode {state} for {client.name}"}
    except ClientNotFoundError as e:
        raise HTTPException(404, str(e))
