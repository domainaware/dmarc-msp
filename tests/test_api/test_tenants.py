"""Tests for the tenant provisioning API endpoints."""

from __future__ import annotations

from tests.test_api.conftest import create_test_client

# --- POST /api/v1/tenants/provision ---


def test_provision_tenant(api_client_with_mocks):
    create_test_client(api_client_with_mocks, "Acme Corp")
    client, mock_os, _, _ = api_client_with_mocks
    mock_os.reset_mock()
    resp = client.post(
        "/api/v1/tenants/provision",
        json={"client_name": "Acme Corp"},
    )
    assert resp.status_code == 200
    assert "acme_corp" in resp.json()["message"]
    mock_os.provision_tenant.assert_called_with("acme_corp")
    mock_os.create_client_role.assert_called_with("acme_corp", "acme_corp")


def test_provision_tenant_not_found(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    resp = client.post(
        "/api/v1/tenants/provision",
        json={"client_name": "Nonexistent"},
    )
    assert resp.status_code == 404


# --- POST /api/v1/tenants/deprovision ---


def test_deprovision_tenant(api_client_with_mocks):
    create_test_client(api_client_with_mocks, "Acme Corp")
    client, mock_os, _, _ = api_client_with_mocks
    mock_os.reset_mock()
    resp = client.post(
        "/api/v1/tenants/deprovision",
        json={"client_name": "Acme Corp"},
    )
    assert resp.status_code == 200
    assert "acme_corp" in resp.json()["message"]
    mock_os.deprovision_tenant.assert_called_with("acme_corp")
    mock_os.delete_client_role.assert_called_with("acme_corp")


def test_deprovision_tenant_not_found(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    resp = client.post(
        "/api/v1/tenants/deprovision",
        json={"client_name": "Nonexistent"},
    )
    assert resp.status_code == 404
