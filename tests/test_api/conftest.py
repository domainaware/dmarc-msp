"""Shared fixtures for API tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from dmarc_msp.api import create_app
from dmarc_msp.config import (
    DatabaseConfig,
    DashboardsConfig,
    DNSProviderConfig,
    MSPConfig,
    OpenSearchConfig,
    ParsedmarcConfig,
    ServerConfig,
    Settings,
)


@pytest.fixture
def api_client(tmp_path):
    """Create a test FastAPI client with a real SQLite DB and mocked services."""
    domain_map = tmp_path / "domain_map.yaml"
    domain_map.write_text("")
    settings = Settings(
        database=DatabaseConfig(url=f"sqlite:///{tmp_path / 'test.db'}"),
        opensearch=OpenSearchConfig(password="test_password", verify_certs=False),
        dashboards=DashboardsConfig(
            url="http://localhost:5601",
            saved_objects_template="/dev/null",
        ),
        msp=MSPConfig(
            domain="dmarc.test.example.com",
            rua_email="reports@dmarc.test.example.com",
        ),
        dns=DNSProviderConfig(provider="cloudflare", zone="test.example.com"),
        parsedmarc=ParsedmarcConfig(domain_map_file=str(domain_map)),
        server=ServerConfig(allowed_ips=[]),
    )
    app = create_app(settings)
    return TestClient(app, raise_server_exceptions=False).__enter__()


def _mock_services():
    """Context manager that patches OpenSearch, Dashboard, and Retention services."""
    return (
        patch("dmarc_msp.api.dependencies.OpenSearchService"),
        patch("dmarc_msp.api.dependencies.DashboardService"),
        patch("dmarc_msp.api.dependencies.RetentionService"),
    )


@pytest.fixture
def api_client_with_mocks(api_client):
    """Yield (client, mock_os, mock_dash, mock_ret) with services patched."""
    with (
        patch("dmarc_msp.api.dependencies.OpenSearchService") as mock_os_cls,
        patch("dmarc_msp.api.dependencies.DashboardService") as mock_dash_cls,
        patch("dmarc_msp.api.dependencies.RetentionService") as mock_ret_cls,
    ):
        mock_os = MagicMock()
        mock_os_cls.return_value = mock_os
        mock_dash = MagicMock()
        mock_dash_cls.return_value = mock_dash
        mock_ret = MagicMock()
        mock_ret_cls.return_value = mock_ret
        yield api_client, mock_os, mock_dash, mock_ret


def create_test_client(api_client_with_mocks, name="Acme Corp", **kwargs):
    """Helper to create a client via the API."""
    client, *_ = api_client_with_mocks
    body = {"name": name, **kwargs}
    resp = client.post("/api/v1/clients", json=body)
    assert resp.status_code == 201
    return resp.json()
