"""OpenSearch multi-tenancy provisioning service."""

from __future__ import annotations

import logging

from opensearchpy import OpenSearch

from dmarc_msp.config import OpenSearchConfig

logger = logging.getLogger(__name__)


class OpenSearchService:
    """Manages OpenSearch tenants, roles, and role mappings for client isolation."""

    def __init__(self, config: OpenSearchConfig):
        self.client = OpenSearch(
            hosts=[config.hosts],
            http_auth=(config.username, config.resolved_password),
            use_ssl=config.ssl,
            verify_certs=config.verify_certs,
            ssl_show_warn=False,
        )

    def provision_tenant(self, tenant_name: str, index_prefix: str) -> None:
        """Create an OpenSearch tenant and its read-only client role (idempotent)."""
        body = {"description": f"Tenant for client: {tenant_name}"}
        self.client.transport.perform_request(
            "PUT",
            f"/_plugins/_security/api/tenants/{tenant_name}",
            body=body,
        )
        logger.info("Provisioned tenant: %s", tenant_name)

        self.create_client_role(tenant_name, index_prefix)

    def deprovision_tenant(self, tenant_name: str) -> None:
        """Delete an OpenSearch tenant, its client role, and role mapping."""
        self.delete_role_mapping(tenant_name)
        self.delete_client_role(tenant_name)

        try:
            self.client.transport.perform_request(
                "DELETE",
                f"/_plugins/_security/api/tenants/{tenant_name}",
            )
            logger.info("Deprovisioned tenant: %s", tenant_name)
        except Exception:
            logger.warning("Tenant '%s' not found for deletion", tenant_name)

    def create_client_role(self, tenant_name: str, index_prefix: str) -> None:
        """Create a role scoped to the client's index prefix and tenant."""
        role_name = f"client_{tenant_name}"
        body = {
            "cluster_permissions": [],
            "index_permissions": [
                {
                    "index_patterns": [f"{index_prefix}-*"],
                    "allowed_actions": [
                        "read",
                        "search",
                        "get",
                        "indices:data/read/*",
                        "indices:admin/mappings/get",
                    ],
                }
            ],
            "tenant_permissions": [
                {
                    "tenant_patterns": [tenant_name],
                    "allowed_actions": ["kibana_all_read"],
                }
            ],
        }
        self.client.transport.perform_request(
            "PUT",
            f"/_plugins/_security/api/roles/{role_name}",
            body=body,
        )
        logger.info("Created role: %s (prefix=%s)", role_name, index_prefix)

    def delete_client_role(self, tenant_name: str) -> None:
        """Delete a client role."""
        role_name = f"client_{tenant_name}"
        try:
            self.client.transport.perform_request(
                "DELETE",
                f"/_plugins/_security/api/roles/{role_name}",
            )
            logger.info("Deleted role: %s", role_name)
        except Exception:
            logger.warning("Role '%s' not found for deletion", role_name)

    def create_role_mapping(
        self, tenant_name: str, backend_roles: list[str] | None = None
    ) -> None:
        """Map users/backend roles to the client role."""
        role_name = f"client_{tenant_name}"
        body: dict = {}
        if backend_roles:
            body["backend_roles"] = backend_roles
        self.client.transport.perform_request(
            "PUT",
            f"/_plugins/_security/api/rolesmapping/{role_name}",
            body=body,
        )
        logger.info("Created role mapping for: %s", role_name)

    def delete_role_mapping(self, tenant_name: str) -> None:
        """Delete the role mapping for a client role."""
        role_name = f"client_{tenant_name}"
        try:
            self.client.transport.perform_request(
                "DELETE",
                f"/_plugins/_security/api/rolesmapping/{role_name}",
            )
            logger.info("Deleted role mapping for: %s", role_name)
        except Exception:
            logger.warning("Role mapping '%s' not found for deletion", role_name)

    def delete_client_indices(self, index_prefix: str) -> None:
        """Delete all indices matching the client's prefix."""
        pattern = f"{index_prefix}-*"
        try:
            self.client.indices.delete(index=pattern)
            logger.info("Deleted indices matching: %s", pattern)
        except Exception:
            logger.warning("No indices found matching: %s", pattern)

    def health(self) -> dict:
        """Return cluster health."""
        return self.client.cluster.health()
