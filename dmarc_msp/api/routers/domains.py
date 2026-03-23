"""Domain management API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dmarc_msp.api.dependencies import DbDep, SettingsDep
from dmarc_msp.api.schemas import DomainAdd, DomainMove, DomainRemove
from dmarc_msp.cli.helpers import get_onboarding_service
from dmarc_msp.models import DomainInfo, MoveResult, OnboardingResult
from dmarc_msp.services.clients import ClientNotFoundError
from dmarc_msp.services.onboarding import DomainAlreadyExistsError, DomainNotFoundError

router = APIRouter()


@router.post("/add", response_model=OnboardingResult, status_code=201)
def add_domain(body: DomainAdd, settings: SettingsDep, db: DbDep):
    try:
        svc = get_onboarding_service(settings, db)
        return svc.add_domain(body.client_name, body.domain)
    except DomainAlreadyExistsError as e:
        raise HTTPException(409, str(e))
    except ClientNotFoundError as e:
        raise HTTPException(404, str(e))


@router.post("/remove")
def remove_domain(body: DomainRemove, settings: SettingsDep, db: DbDep):
    try:
        svc = get_onboarding_service(settings, db)
        client_name = svc.remove_domain(body.domain, purge_dns=not body.keep_dns)
        return {"message": f"Removed {body.domain} from {client_name}"}
    except DomainNotFoundError as e:
        raise HTTPException(404, str(e))


@router.post("/move", response_model=MoveResult)
def move_domain(body: DomainMove, settings: SettingsDep, db: DbDep):
    try:
        svc = get_onboarding_service(settings, db)
        return svc.move_domain(body.domain, body.to_client)
    except DomainNotFoundError as e:
        raise HTTPException(404, str(e))
    except DomainAlreadyExistsError as e:
        raise HTTPException(409, str(e))
    except ClientNotFoundError as e:
        raise HTTPException(404, str(e))


@router.get("", response_model=list[DomainInfo])
def list_domains(
    settings: SettingsDep,
    db: DbDep,
    client: str | None = None,
):
    from dmarc_msp.db import DomainRow
    from dmarc_msp.services.clients import ClientService

    query = db.query(DomainRow)
    if client:
        client_svc = ClientService(db)
        try:
            client_row = client_svc.get(client)
        except ClientNotFoundError as e:
            raise HTTPException(404, str(e))
        query = query.filter(DomainRow.client_id == client_row.id)

    domains = query.order_by(DomainRow.domain_name).all()
    return [DomainInfo.model_validate(d) for d in domains]
