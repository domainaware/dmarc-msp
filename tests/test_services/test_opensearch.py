"""Tests for OpenSearch provisioning service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from opensearchpy import NotFoundError

from dmarc_msp.config import OpenSearchConfig
from dmarc_msp.services.opensearch import OpenSearchService, UserNotFoundError


def _make_service() -> tuple[OpenSearchService, MagicMock]:
    config = OpenSearchConfig(password="test_password", verify_certs=False)
    with patch("dmarc_msp.services.opensearch.OpenSearch"):
        svc = OpenSearchService(config)
    mock_client = MagicMock()
    svc.client = mock_client  # type: ignore[assignment]
    return svc, mock_client


def test_provision_tenant():
    svc, mock_client = _make_service()
    svc.provision_tenant("client_acme_corp", "acme_corp")
    calls = mock_client.transport.perform_request.call_args_list
    assert len(calls) == 2
    # First call: tenant creation
    assert calls[0][0] == ("PUT", "/_plugins/_security/api/tenants/client_acme_corp")
    assert calls[0][1]["body"] == {"description": "Tenant for client: client_acme_corp"}
    # Second call: client role creation (role_name = tenant_name)
    assert calls[1][0][0] == "PUT"
    assert "client_acme_corp" in calls[1][0][1]
    body = calls[1][1]["body"]
    assert body["cluster_permissions"] == [
        "cluster:admin/opensearch/ql/datasources/read",
        "cluster_composite_ops_ro",
    ]
    assert body["index_permissions"][0]["index_patterns"] == [
        "acme_corp_dmarc_aggregate*",
        "acme_corp_dmarc_fo*",
        "acme_corp_smtp_tls*",
    ]
    assert body["index_permissions"][0]["allowed_actions"] == ["read"]
    assert body["tenant_permissions"][0]["allowed_actions"] == ["kibana_all_read"]


def test_deprovision_tenant():
    svc, mock_client = _make_service()
    svc.deprovision_tenant("client_acme_corp")
    calls = mock_client.transport.perform_request.call_args_list
    assert len(calls) == 3
    # Deletes role mapping, role, then tenant (role_name = tenant_name)
    assert calls[0][0] == (
        "DELETE",
        "/_plugins/_security/api/rolesmapping/client_acme_corp",
    )
    assert calls[1][0] == (
        "DELETE",
        "/_plugins/_security/api/roles/client_acme_corp",
    )
    assert calls[2][0] == ("DELETE", "/_plugins/_security/api/tenants/client_acme_corp")


def test_deprovision_tenant_not_found():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.side_effect = NotFoundError(404, "not found")
    # Should not raise
    svc.deprovision_tenant("client_acme_corp")


def test_create_client_role():
    svc, mock_client = _make_service()
    svc.create_client_role("client_acme_corp", "acme")
    call = mock_client.transport.perform_request.call_args
    assert call[0][0] == "PUT"
    assert "client_acme_corp" in call[0][1]
    body = call[1]["body"]
    assert body["cluster_permissions"] == [
        "cluster:admin/opensearch/ql/datasources/read",
        "cluster_composite_ops_ro",
    ]
    assert body["index_permissions"][0]["index_patterns"] == [
        "acme_dmarc_aggregate*",
        "acme_dmarc_fo*",
        "acme_smtp_tls*",
    ]
    assert body["index_permissions"][0]["allowed_actions"] == ["read"]
    assert body["tenant_permissions"][0]["tenant_patterns"] == ["client_acme_corp"]


def test_delete_client_role():
    svc, mock_client = _make_service()
    svc.delete_client_role("client_acme_corp")
    mock_client.transport.perform_request.assert_called_once_with(
        "DELETE",
        "/_plugins/_security/api/roles/client_acme_corp",
    )


def test_delete_client_role_not_found():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.side_effect = NotFoundError(404, "not found")
    # Should not raise
    svc.delete_client_role("client_acme_corp")


def test_create_role_mapping_with_backend_roles():
    svc, mock_client = _make_service()
    svc.create_role_mapping("client_acme_corp", backend_roles=["admin"])
    call = mock_client.transport.perform_request.call_args
    assert call[0][0] == "PUT"
    assert call[1]["body"]["backend_roles"] == ["admin"]


def test_create_role_mapping_without_backend_roles():
    svc, mock_client = _make_service()
    svc.create_role_mapping("client_acme_corp")
    call = mock_client.transport.perform_request.call_args
    assert "backend_roles" not in call[1]["body"]


def test_delete_client_indices():
    svc, mock_client = _make_service()
    svc.delete_client_indices("acme")
    mock_client.indices.delete.assert_called_once_with(index="acme_*")


def test_delete_client_indices_not_found():
    svc, mock_client = _make_service()
    mock_client.indices.delete.side_effect = NotFoundError(404, "index not found")
    # Should not raise
    svc.delete_client_indices("acme")


def test_health():
    svc, mock_client = _make_service()
    mock_client.cluster.health.return_value = {"status": "green"}
    result = svc.health()
    assert result["status"] == "green"


# ── Internal user management tests ──────────────────────────────────


def test_create_internal_user():
    svc, mock_client = _make_service()
    svc.create_internal_user(
        "analyst1",
        "secret123",
        backend_roles=["kibana_read_only"],
        attributes={"role_type": "analyst"},
        description="Test analyst",
    )
    call = mock_client.transport.perform_request.call_args
    assert call[0] == ("PUT", "/_plugins/_security/api/internalusers/analyst1")
    body = call[1]["body"]
    assert body["password"] == "secret123"
    assert body["backend_roles"] == ["kibana_read_only"]
    assert body["attributes"]["role_type"] == "analyst"
    assert body["description"] == "Test analyst"


def test_delete_internal_user():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.side_effect = [
        {"analyst1": {"attributes": {}}},  # _check_user_exists
        None,  # DELETE
    ]
    svc.delete_internal_user("analyst1")
    delete_call = mock_client.transport.perform_request.call_args
    assert delete_call[0] == (
        "DELETE",
        "/_plugins/_security/api/internalusers/analyst1",
    )


def test_get_internal_user():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.return_value = {
        "analyst1": {"attributes": {"role_type": "analyst"}}
    }
    result = svc.get_internal_user("analyst1")
    assert result["attributes"]["role_type"] == "analyst"


def test_get_internal_user_not_found():
    svc, mock_client = _make_service()
    # List returns users, but not the one we're looking for
    mock_client.transport.perform_request.return_value = {"admin": {}}
    with pytest.raises(UserNotFoundError, match="nonexistent"):
        svc.get_internal_user("nonexistent")


def test_get_internal_user_connection_error():
    svc, mock_client = _make_service()
    # Connection error should propagate as-is, not be swallowed
    mock_client.transport.perform_request.side_effect = ConnectionError("refused")
    with pytest.raises(ConnectionError):
        svc.get_internal_user("analyst1")


def test_delete_internal_user_not_found():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.return_value = {"admin": {}}
    with pytest.raises(UserNotFoundError, match="nonexistent"):
        svc.delete_internal_user("nonexistent")


def test_update_password_user_not_found():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.return_value = {"admin": {}}
    with pytest.raises(UserNotFoundError, match="nonexistent"):
        svc.update_internal_user_password("nonexistent", "newpass")


def test_disable_user_not_found():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.return_value = {"admin": {}}
    with pytest.raises(UserNotFoundError, match="nonexistent"):
        svc.disable_user("nonexistent")


def test_list_internal_users():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.return_value = {
        "admin": {},
        "analyst1": {"attributes": {"role_type": "analyst"}},
    }
    result = svc.list_internal_users()
    assert "analyst1" in result
    assert "admin" in result


def test_update_internal_user_password():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.side_effect = [
        {"analyst1": {"attributes": {}}},  # _check_user_exists
        None,  # PATCH
    ]
    svc.update_internal_user_password("analyst1", "newpass")
    patch_call = mock_client.transport.perform_request.call_args
    assert patch_call[0] == (
        "PATCH",
        "/_plugins/_security/api/internalusers/analyst1",
    )
    assert patch_call[1]["body"] == {"password": "newpass"}


def test_add_user_to_role_mapping_creates_new():
    svc, mock_client = _make_service()
    # GET raises 404 (no existing mapping)
    mock_client.transport.perform_request.side_effect = [
        NotFoundError(404, "not found"),
        None,  # PUT succeeds
    ]
    svc.add_user_to_role_mapping("analyst", "user1")
    put_call = mock_client.transport.perform_request.call_args
    assert put_call[0] == (
        "PUT",
        "/_plugins/_security/api/rolesmapping/analyst",
    )
    assert put_call[1]["body"]["users"] == ["user1"]


def test_add_user_to_role_mapping_appends():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.side_effect = [
        {"analyst": {"users": ["existing_user"]}},  # GET
        None,  # PUT
    ]
    svc.add_user_to_role_mapping("analyst", "user1")
    put_call = mock_client.transport.perform_request.call_args
    assert put_call[1]["body"]["users"] == ["existing_user", "user1"]


def test_add_user_to_role_mapping_idempotent():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.side_effect = [
        {"analyst": {"users": ["user1"]}},  # GET — user already present
        None,  # PUT
    ]
    svc.add_user_to_role_mapping("analyst", "user1")
    put_call = mock_client.transport.perform_request.call_args
    assert put_call[1]["body"]["users"] == ["user1"]


def test_remove_user_from_role_mapping():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.side_effect = [
        {"analyst": {"users": ["user1", "user2"]}},  # GET
        None,  # PUT
    ]
    svc.remove_user_from_role_mapping("analyst", "user1")
    put_call = mock_client.transport.perform_request.call_args
    assert put_call[1]["body"]["users"] == ["user2"]


def test_remove_user_from_role_mapping_not_found():
    svc, mock_client = _make_service()
    mock_client.transport.perform_request.side_effect = NotFoundError(404, "not found")
    # Should not raise
    svc.remove_user_from_role_mapping("analyst", "user1")


def test_ensure_analyst_role():
    svc, mock_client = _make_service()
    svc.ensure_analyst_role()
    call = mock_client.transport.perform_request.call_args
    assert call[0] == ("PUT", "/_plugins/_security/api/roles/analyst")
    body = call[1]["body"]
    assert body["cluster_permissions"] == [
        "cluster:admin/opensearch/ql/datasources/read",
        "cluster_composite_ops_ro",
    ]
    assert body["index_permissions"][0]["index_patterns"] == [
        "*_dmarc_aggregate*",
        "*_dmarc_fo*",
        "*_smtp_tls*",
    ]
    assert body["index_permissions"][0]["allowed_actions"] == ["read"]
    assert body["tenant_permissions"][0]["tenant_patterns"] == ["client_*"]
    assert body["tenant_permissions"][0]["allowed_actions"] == ["kibana_all_read"]


def test_disable_user():
    svc, mock_client = _make_service()
    import json

    roles = ["analyst", "kibana_read_only"]
    user_data = {
        "testuser": {
            "attributes": {
                "role_type": "analyst",
                "roles": json.dumps(roles),
                "disabled": "false",
            }
        }
    }
    # Calls: GET users (get_internal_user),
    #        GET users + PATCH (update_internal_user_password),
    #        GET+PUT mapping (analyst), GET+PUT mapping (kibana),
    #        GET users + PATCH (update_internal_user_attributes)
    mock_client.transport.perform_request.side_effect = [
        user_data,  # _check_user_exists (get_internal_user)
        user_data,  # _check_user_exists (update_internal_user_password)
        None,  # PATCH password
        {"analyst": {"users": ["testuser"]}},  # GET mapping for analyst
        None,  # PUT mapping for analyst
        {"kibana_read_only": {"users": ["testuser"]}},  # GET mapping for kibana
        None,  # PUT mapping for kibana
        user_data,  # _check_user_exists (update_internal_user_attributes)
        None,  # PATCH attributes
    ]
    result = svc.disable_user("testuser")
    assert result == roles


def test_restore_user_roles():
    svc, mock_client = _make_service()
    import json

    roles = ["analyst", "kibana_read_only"]
    user_data = {
        "testuser": {
            "attributes": {
                "role_type": "analyst",
                "roles": json.dumps(roles),
                "disabled": "true",
            }
        }
    }
    # Calls: GET users (get_internal_user),
    #        GET+PUT mapping (analyst), GET+PUT mapping (kibana),
    #        GET users + PATCH (update_internal_user_attributes)
    mock_client.transport.perform_request.side_effect = [
        user_data,  # _check_user_exists (get_internal_user)
        NotFoundError(404, "not found"),  # GET mapping for analyst (doesn't exist)
        None,  # PUT mapping for analyst
        NotFoundError(404, "not found"),  # GET mapping for kibana
        None,  # PUT mapping for kibana
        user_data,  # _check_user_exists (update_internal_user_attributes)
        None,  # PATCH attributes
    ]
    result = svc.restore_user_roles("testuser")
    assert result == roles


def test_restore_user_roles_not_disabled():
    svc, mock_client = _make_service()
    import json

    user_data = {
        "testuser": {
            "attributes": {
                "role_type": "analyst",
                "roles": json.dumps(["analyst"]),
                "disabled": "false",
            }
        }
    }
    mock_client.transport.perform_request.return_value = user_data
    result = svc.restore_user_roles("testuser")
    assert result == []
