"""FastAPI application for dmarc-msp management API."""

from __future__ import annotations

from fastapi import FastAPI

from dmarc_msp.api.dependencies import lifespan
from dmarc_msp.api.middleware import IPAllowlistMiddleware
from dmarc_msp.api.routers import (
    clients,
    dashboards,
    domains,
    parsedmarc,
    retention,
    tenants,
)
from dmarc_msp.config import Settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        from dmarc_msp.config import load_settings

        settings = load_settings()

    app = FastAPI(
        title="DMARC for MSPs",
        version="0.1.0",
        description="Management API for DMARC monitoring automation.",
        lifespan=lifespan,
    )

    # Store settings for dependency injection
    app.state.settings = settings

    # IP allowlist middleware
    app.add_middleware(
        IPAllowlistMiddleware,
        allowed_ips=settings.server.allowed_ips,
    )

    # Register routers
    app.include_router(clients.router, prefix="/api/v1/clients", tags=["clients"])
    app.include_router(domains.router, prefix="/api/v1/domains", tags=["domains"])
    app.include_router(tenants.router, prefix="/api/v1/tenants", tags=["tenants"])
    app.include_router(
        dashboards.router, prefix="/api/v1/dashboard", tags=["dashboard"]
    )
    app.include_router(
        parsedmarc.router, prefix="/api/v1/parsedmarc", tags=["parsedmarc"]
    )
    app.include_router(retention.router, prefix="/api/v1/retention", tags=["retention"])

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app
