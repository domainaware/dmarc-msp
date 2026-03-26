"""Tests for OpenSearch provisioning service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from dmarc_msp.config import OpenSearchConfig
from dmarc_msp.services.opensearch import OpenSearchService


def _make_service() -> tuple[OpenSearchService, MagicMock]:
    config = OpenSearchConfig(password="test_password", verify_certs=False)
    with patch("dmarc_msp.services.opensearch.OpenSearch"):
        svc = OpenSearchService(config)
    mock_client = MagicMock()
    svc.client = mock_client  # type: ignore[assignment]
    return svc, mock_client


def test_provision_tenant():
    svc, mock_client = _make_service()
    svc.provision_tenant("acme_corp", "acme_corp")
    calls = mock_client.transport.perform_request.call_args_list
    assert len(calls) == 2
    # First call: tenant creation
    assert calls[0][0] == ("PUT", "/_plugins/_security/api/tenants/acme_corp")
    assert calls[0][1]["body"] == {"description": "Tenant for client: acme_corp"}
    # Second call: client role creation
    assert calls[1][0][0] == "PUT"
    assert "client_acme_corp" in calls[1][0][1]
    body = calls[1][1]["body"]
    assert body["index_permissions"][0]["index_patterns"] == ["acme_corp-*"]
    assert body["tenant_permissions"][0]["allowed_actions"] == ["kibana_all_read"]


def test_deprovision_tenant():
    svc, mock_client = _make_service()
    svc.deprovision_tenant("acme_corp")
    calls = mock_client.transport.perform_request.call_args_list
    assert len(calls) == 3
    # Deletes role mapping, role, then tenant
    assert calls[0][0] == (
        "DELETE",
        "/_plugins/_security/api/rolesmapping/client_acme_corp",
    )
    assert calls[1][0] == (
        "DELETE",
        "/_plugins/_security/api/roles/client_acme_corp",
    )
    assert calls[2][0] == ("DELETE", "/_plugins/_security/api/tenants/acme_corp")


def test_deprovision_tenant_not_found():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.side_effect = Exception("not found")
    # Should not raise
    svc.deprovision_tenant("acme_corp")


def test_create_client_role():
    svc, mock_client = _make_service()
    svc.create_client_role("acme_corp", "acme")
    call = mock_client.transport.perform_request.call_args
    assert call[0][0] == "PUT"
    assert "client_acme_corp" in call[0][1]
    body = call[1]["body"]
    assert body["index_permissions"][0]["index_patterns"] == ["acme-*"]
    assert body["tenant_permissions"][0]["tenant_patterns"] == ["acme_corp"]


def test_delete_client_role():
    svc, mock_client = _make_service()
    svc.delete_client_role("acme_corp")
    mock_client.transport.perform_request.assert_called_once_with(
        "DELETE",
        "/_plugins/_security/api/roles/client_acme_corp",
    )


def test_delete_client_role_not_found():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.side_effect = Exception("not found")
    # Should not raise
    svc.delete_client_role("acme_corp")


def test_create_role_mapping_with_backend_roles():
    svc, mock_client = _make_service()
    svc.create_role_mapping("acme_corp", backend_roles=["admin"])
    call = mock_client.transport.perform_request.call_args
    assert call[0][0] == "PUT"
    assert call[1]["body"]["backend_roles"] == ["admin"]


def test_create_role_mapping_without_backend_roles():
    svc, mock_client = _make_service()
    svc.create_role_mapping("acme_corp")
    call = mock_client.transport.perform_request.call_args
    assert "backend_roles" not in call[1]["body"]


def test_delete_client_indices():
    svc, mock_client = _make_service()
    svc.delete_client_indices("acme")
    mock_client.indices.delete.assert_called_once_with(index="acme-*")


def test_delete_client_indices_not_found():
    svc, mock_client = _make_service()
    mock_client.indices.delete.side_effect = Exception("index not found")
    # Should not raise
    svc.delete_client_indices("acme")


def test_health():
    svc, mock_client = _make_service()
    mock_client.cluster.health.return_value = {"status": "green"}
    result = svc.health()
    assert result["status"] == "green"
