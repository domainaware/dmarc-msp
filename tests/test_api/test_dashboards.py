"""Tests for the dashboard import API endpoints."""

from __future__ import annotations

from tests.test_api.conftest import create_test_client

# --- POST /api/v1/dashboard/import ---


def test_import_dashboards(api_client_with_mocks):
    create_test_client(api_client_with_mocks, "Acme Corp")
    client, _, mock_dash, _ = api_client_with_mocks
    mock_dash.reset_mock()
    resp = client.post(
        "/api/v1/dashboard/import",
        json={"client_name": "Acme Corp"},
    )
    assert resp.status_code == 200
    assert "acme corp" in resp.json()["message"]
    mock_dash.import_for_client.assert_called_with("client_acme_corp", "acme_corp")


def test_import_dashboards_client_not_found(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    resp = client.post(
        "/api/v1/dashboard/import",
        json={"client_name": "Nonexistent"},
    )
    assert resp.status_code == 404


def test_dark_mode_enable(api_client_with_mocks):
    create_test_client(api_client_with_mocks, "Acme Corp")
    client, _, mock_dash, _ = api_client_with_mocks
    mock_dash.reset_mock()
    resp = client.post(
        "/api/v1/dashboard/dark-mode",
        json={"client_name": "Acme Corp", "enabled": True},
    )
    assert resp.status_code == 200
    assert "enabled" in resp.json()["message"]
    mock_dash.set_dark_mode.assert_called_with("client_acme_corp", True)


def test_dark_mode_disable(api_client_with_mocks):
    create_test_client(api_client_with_mocks, "Acme Corp")
    client, _, mock_dash, _ = api_client_with_mocks
    mock_dash.reset_mock()
    resp = client.post(
        "/api/v1/dashboard/dark-mode",
        json={"client_name": "Acme Corp", "enabled": False},
    )
    assert resp.status_code == 200
    assert "disabled" in resp.json()["message"]
    mock_dash.set_dark_mode.assert_called_with("client_acme_corp", False)


def test_dark_mode_client_not_found(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    resp = client.post(
        "/api/v1/dashboard/dark-mode",
        json={"client_name": "Nonexistent", "enabled": True},
    )
    assert resp.status_code == 404


def test_import_dashboards_template_missing(api_client_with_mocks):
    create_test_client(api_client_with_mocks, "Acme Corp")
    client, _, mock_dash, _ = api_client_with_mocks
    mock_dash.import_for_client.side_effect = FileNotFoundError("missing")
    resp = client.post(
        "/api/v1/dashboard/import",
        json={"client_name": "Acme Corp"},
    )
    assert resp.status_code == 500
