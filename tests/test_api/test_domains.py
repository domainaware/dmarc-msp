"""Tests for the domain management API endpoints."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.test_api.conftest import create_test_client


def _patch_onboarding():
    return patch("dmarc_msp.api.routers.domains.get_onboarding_service")


# --- POST /api/v1/domains/add ---


def test_add_domain(api_client_with_mocks):
    create_test_client(api_client_with_mocks, "Acme Corp")
    client, *_ = api_client_with_mocks
    with _patch_onboarding() as mock_get_svc:
        mock_svc = MagicMock()
        mock_svc.add_domain.return_value = MagicMock(
            client_name="acme corp",
            domain="acme.com",
            dns_verified=True,
            tenant="acme_corp",
            index_prefix="acme_corp",
        )
        mock_get_svc.return_value = mock_svc
        resp = client.post(
            "/api/v1/domains/add",
            json={"client_name": "Acme Corp", "domain": "acme.com"},
        )
    assert resp.status_code == 201
    assert resp.json()["domain"] == "acme.com"


def test_add_domain_duplicate(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    with _patch_onboarding() as mock_get_svc:
        from dmarc_msp.services.onboarding import DomainAlreadyExistsError

        mock_svc = MagicMock()
        mock_svc.add_domain.side_effect = DomainAlreadyExistsError("exists")
        mock_get_svc.return_value = mock_svc
        resp = client.post(
            "/api/v1/domains/add",
            json={"client_name": "Acme Corp", "domain": "acme.com"},
        )
    assert resp.status_code == 409


def test_add_domain_client_not_found(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    with _patch_onboarding() as mock_get_svc:
        from dmarc_msp.services.clients import ClientNotFoundError

        mock_svc = MagicMock()
        mock_svc.add_domain.side_effect = ClientNotFoundError("not found")
        mock_get_svc.return_value = mock_svc
        resp = client.post(
            "/api/v1/domains/add",
            json={"client_name": "Nonexistent", "domain": "acme.com"},
        )
    assert resp.status_code == 404


# --- POST /api/v1/domains/remove ---


def test_remove_domain(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    with _patch_onboarding() as mock_get_svc:
        mock_svc = MagicMock()
        mock_svc.remove_domain.return_value = "acme corp"
        mock_get_svc.return_value = mock_svc
        resp = client.post(
            "/api/v1/domains/remove",
            json={"domain": "acme.com"},
        )
    assert resp.status_code == 200
    assert "acme corp" in resp.json()["message"]


def test_remove_domain_keep_dns(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    with _patch_onboarding() as mock_get_svc:
        mock_svc = MagicMock()
        mock_svc.remove_domain.return_value = "acme corp"
        mock_get_svc.return_value = mock_svc
        resp = client.post(
            "/api/v1/domains/remove",
            json={"domain": "acme.com", "keep_dns": True},
        )
    assert resp.status_code == 200
    mock_svc.remove_domain.assert_called_once_with("acme.com", purge_dns=False)


def test_remove_domain_not_found(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    with _patch_onboarding() as mock_get_svc:
        from dmarc_msp.services.onboarding import DomainNotFoundError

        mock_svc = MagicMock()
        mock_svc.remove_domain.side_effect = DomainNotFoundError("not found")
        mock_get_svc.return_value = mock_svc
        resp = client.post(
            "/api/v1/domains/remove",
            json={"domain": "nonexistent.com"},
        )
    assert resp.status_code == 404


# --- POST /api/v1/domains/move ---


def test_move_domain(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    with _patch_onboarding() as mock_get_svc:
        mock_svc = MagicMock()
        mock_svc.move_domain.return_value = MagicMock(
            domain="acme.com",
            from_client="acme corp",
            to_client="healthco",
        )
        mock_get_svc.return_value = mock_svc
        resp = client.post(
            "/api/v1/domains/move",
            json={"domain": "acme.com", "to_client": "HealthCo"},
        )
    assert resp.status_code == 200
    assert resp.json()["to_client"] == "healthco"


def test_move_domain_not_found(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    with _patch_onboarding() as mock_get_svc:
        from dmarc_msp.services.onboarding import DomainNotFoundError

        mock_svc = MagicMock()
        mock_svc.move_domain.side_effect = DomainNotFoundError("not found")
        mock_get_svc.return_value = mock_svc
        resp = client.post(
            "/api/v1/domains/move",
            json={"domain": "x.com", "to_client": "Y"},
        )
    assert resp.status_code == 404


def test_move_domain_same_client(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    with _patch_onboarding() as mock_get_svc:
        from dmarc_msp.services.onboarding import DomainAlreadyExistsError

        mock_svc = MagicMock()
        mock_svc.move_domain.side_effect = DomainAlreadyExistsError("same")
        mock_get_svc.return_value = mock_svc
        resp = client.post(
            "/api/v1/domains/move",
            json={"domain": "acme.com", "to_client": "Acme Corp"},
        )
    assert resp.status_code == 409


# --- GET /api/v1/domains ---


def test_list_domains_empty(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    resp = client.get("/api/v1/domains")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_domains_filter_by_client_not_found(api_client_with_mocks):
    client, *_ = api_client_with_mocks
    resp = client.get("/api/v1/domains?client=nonexistent")
    assert resp.status_code == 404
