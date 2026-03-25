"""FastAPI dependency injection."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Request
from sqlalchemy.orm import Session

from dmarc_msp.config import Settings
from dmarc_msp.db import init_db
from dmarc_msp.services.clients import ClientService
from dmarc_msp.services.dashboards import DashboardService
from dmarc_msp.services.opensearch import OpenSearchService
from dmarc_msp.services.retention import RetentionService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Initialize DB on startup."""
    settings: Settings = app.state.settings
    app.state.session_factory = init_db(settings.database.url)
    yield


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Generator[Session]:
    session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[Session, Depends(get_db)]


def get_client_service(db: DbDep) -> ClientService:
    return ClientService(db)


def get_opensearch_service(settings: SettingsDep) -> OpenSearchService:
    return OpenSearchService(settings.opensearch)


def get_dashboard_service(settings: SettingsDep) -> DashboardService:
    return DashboardService(settings.dashboards, settings.opensearch)


def get_retention_service(settings: SettingsDep) -> RetentionService:
    return RetentionService(settings.opensearch, settings.retention)


ClientServiceDep = Annotated[ClientService, Depends(get_client_service)]
OpenSearchServiceDep = Annotated[OpenSearchService, Depends(get_opensearch_service)]
DashboardServiceDep = Annotated[DashboardService, Depends(get_dashboard_service)]
RetentionServiceDep = Annotated[RetentionService, Depends(get_retention_service)]
