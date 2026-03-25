"""Tests for the client management API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.test_api.conftest import create_test_client

# --- POST /api/v1/clients ---


def test_create_client_success(api_client_with_mocks):
    client, mock_os, mock_dash, _ = api_client_with_mocks
    resp = client.post(
        "/api/v1/clients",
        json={"name": "Acme Corp", "contact_email": "test@acme.com"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "acme corp"
    assert data["index_prefix"] == "acme_corp"
    assert data["contact_email"] == "test@acme.com"
    mock_os.health.assert_called_once()
    mock_os.provision_tenant.assert_called_once()
    mock_os.create_client_role.assert_called_once()
    mock_dash.import_for_client.assert_called_once()


def test_create_client_with_retention(api_client_with_mocks):
    client, _, _, mock_ret = api_client_with_mocks
    resp = client.post(
        "/api/v1/clients",
        json={"name": "Acme Corp", "retention_days": 365},
    )
    assert resp.status_code == 201
    mock_ret.create_client_policy.assert_called_once_with("acme_corp", 365)


def test_create_client_opensearch_unreachable(api_client):
    with patch("dmarc_msp.api.dependencies.OpenSearchService") as mock_os_cls:
        mock_os = MagicMock()
        mock_os.health.side_effect = ConnectionError("Connection refused")
        mock_os_cls.return_value = mock_os
        resp = api_client.post("/api/v1/clients", json={"name": "Acme Corp"})
    assert resp.status_code == 503
    assert "Cannot connect to OpenSearch" in resp.json()["detail"]


def test_create_client_no_db_entry_on_opensearch_failure(api_client_with_mocks):
    client, mock_os, _, _ = api_client_with_mocks
    mock_os.health.side_effect = ConnectionError("fail")
    client.post("/api/v1/clients", json={"name": "Acme Corp"})
    mock_os.health.side_effect = None  # restore for list call
    resp = client.get("/api/v1/clients")
    assert resp.json() == []


def test_create_client_duplicate_returns_409(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    client.post("/api/v1/clients", json={"name": "Acme Corp"})
    resp = client.post("/api/v1/clients", json={"name": "Acme Corp"})
    assert resp.status_code == 409


def test_create_client_provisioning_failure_returns_500(api_client_with_mocks):
    client, mock_os, _, _ = api_client_with_mocks
    mock_os.provision_tenant.side_effect = RuntimeError("tenant failed")
    resp = client.post("/api/v1/clients", json={"name": "Acme Corp"})
    assert resp.status_code == 500


# --- GET /api/v1/clients ---


def test_list_clients_empty(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    resp = client.get("/api/v1/clients")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_clients(api_client_with_mocks):
    create_test_client(api_client_with_mocks, "Acme Corp")
    create_test_client(api_client_with_mocks, "HealthCo")
    client, *_ = api_client_with_mocks
    resp = client.get("/api/v1/clients")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


# --- GET /api/v1/clients/{name} ---


def test_get_client(api_client_with_mocks):
    create_test_client(api_client_with_mocks, "Acme Corp")
    client, *_ = api_client_with_mocks
    resp = client.get("/api/v1/clients/acme corp")
    assert resp.status_code == 200
    assert resp.json()["name"] == "acme corp"


def test_get_client_not_found(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    resp = client.get("/api/v1/clients/nonexistent")
    assert resp.status_code == 404


# --- PATCH /api/v1/clients/{name} ---


def test_update_client(api_client_with_mocks):
    create_test_client(api_client_with_mocks, "Acme Corp")
    client, *_ = api_client_with_mocks
    resp = client.patch(
        "/api/v1/clients/acme corp",
        json={"contact_email": "new@acme.com"},
    )
    assert resp.status_code == 200
    assert resp.json()["contact_email"] == "new@acme.com"


def test_update_client_not_found(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    resp = client.patch(
        "/api/v1/clients/nonexistent",
        json={"contact_email": "x@y.com"},
    )
    assert resp.status_code == 404


# --- POST /api/v1/clients/{name}/rename ---


def test_rename_client(api_client_with_mocks):
    create_test_client(api_client_with_mocks, "Acme Corp")
    client, *_ = api_client_with_mocks
    resp = client.post(
        "/api/v1/clients/acme corp/rename",
        json={"new_name": "Acme Inc"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "acme inc"
    assert resp.json()["index_prefix"] == "acme_corp"  # unchanged


def test_rename_client_not_found(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    resp = client.post(
        "/api/v1/clients/nonexistent/rename",
        json={"new_name": "New Name"},
    )
    assert resp.status_code == 404


def test_rename_client_conflict(api_client_with_mocks):
    create_test_client(api_client_with_mocks, "Acme Corp")
    create_test_client(api_client_with_mocks, "HealthCo")
    client, *_ = api_client_with_mocks
    resp = client.post(
        "/api/v1/clients/acme corp/rename",
        json={"new_name": "HealthCo"},
    )
    assert resp.status_code == 409


# --- POST /api/v1/clients/{name}/offboard ---


def test_offboard_client(api_client_with_mocks):
    create_test_client(api_client_with_mocks, "Acme Corp")
    client, *_ = api_client_with_mocks
    with (
        patch("dmarc_msp.api.routers.clients.get_offboarding_service") as mock_get_svc,
    ):
        mock_svc = MagicMock()
        mock_svc.offboard_client.return_value = MagicMock(
            client_name="acme corp", domains_removed=0
        )
        mock_get_svc.return_value = mock_svc
        resp = client.post(
            "/api/v1/clients/acme corp/offboard",
            json={"purge_indices": False},
        )
    assert resp.status_code == 200
    assert resp.json()["domains_removed"] == 0


def test_offboard_client_not_found(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    with patch("dmarc_msp.api.routers.clients.get_offboarding_service") as mock_get_svc:
        from dmarc_msp.services.clients import ClientNotFoundError

        mock_svc = MagicMock()
        mock_svc.offboard_client.side_effect = ClientNotFoundError("not found")
        mock_get_svc.return_value = mock_svc
        resp = client.post(
            "/api/v1/clients/nonexistent/offboard",
            json={"purge_indices": False},
        )
    assert resp.status_code == 404


# --- GET /health ---


def test_health(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
