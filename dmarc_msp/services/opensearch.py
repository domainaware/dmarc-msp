"""OpenSearch multi-tenancy provisioning and user management service."""

from __future__ import annotations

import json
import logging
import secrets

from opensearchpy import NotFoundError, OpenSearch

from dmarc_msp.config import OpenSearchConfig

logger = logging.getLogger(__name__)


class UserNotFoundError(Exception):
    pass


class UserAlreadyExistsError(Exception):
    pass


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
        except NotFoundError:
            logger.warning("Tenant '%s' not found for deletion", tenant_name)

    def create_client_role(self, tenant_name: str, index_prefix: str) -> None:
        """Create a role scoped to the client's index prefix and tenant."""
        role_name = tenant_name
        body = {
            "cluster_permissions": [],
            "index_permissions": [
                {
                    "index_patterns": [f"{index_prefix}_*"],
                    "allowed_actions": ["read", "search", "get"],
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
        role_name = tenant_name
        try:
            self.client.transport.perform_request(
                "DELETE",
                f"/_plugins/_security/api/roles/{role_name}",
            )
            logger.info("Deleted role: %s", role_name)
        except NotFoundError:
            logger.warning("Role '%s' not found for deletion", role_name)

    def create_role_mapping(
        self, tenant_name: str, backend_roles: list[str] | None = None
    ) -> None:
        """Map users/backend roles to the client role."""
        role_name = tenant_name
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
        role_name = tenant_name
        try:
            self.client.transport.perform_request(
                "DELETE",
                f"/_plugins/_security/api/rolesmapping/{role_name}",
            )
            logger.info("Deleted role mapping for: %s", role_name)
        except NotFoundError:
            logger.warning("Role mapping '%s' not found for deletion", role_name)

    def delete_client_indices(self, index_prefix: str) -> None:
        """Delete all indices matching the client's prefix."""
        pattern = f"{index_prefix}_*"
        try:
            self.client.indices.delete(index=pattern)
            logger.info("Deleted indices matching: %s", pattern)
        except NotFoundError:
            logger.warning("No indices found matching: %s", pattern)

    def health(self) -> dict:
        """Return cluster health."""
        return self.client.cluster.health()

    # ── Internal user management ──────────────────────────────────────

    def create_internal_user(
        self,
        username: str,
        password: str,
        backend_roles: list[str] | None = None,
        attributes: dict[str, str] | None = None,
        description: str = "",
    ) -> None:
        """Create an OpenSearch internal user."""
        all_users = self.client.transport.perform_request(
            "GET",
            "/_plugins/_security/api/internalusers/",
        )
        if username in all_users:
            raise UserAlreadyExistsError(f"User '{username}' already exists")
        body: dict = {
            "password": password,
            "backend_roles": backend_roles or [],
            "attributes": attributes or {},
            "description": description,
        }
        self.client.transport.perform_request(
            "PUT",
            f"/_plugins/_security/api/internalusers/{username}",
            body=body,
        )
        logger.info("Created internal user: %s", username)

    def _check_user_exists(self, username: str) -> dict:
        """Fetch user details or raise UserNotFoundError."""
        all_users = self.client.transport.perform_request(
            "GET",
            "/_plugins/_security/api/internalusers/",
        )
        if username not in all_users:
            raise UserNotFoundError(f"User '{username}' not found")
        return all_users[username]

    def delete_internal_user(self, username: str) -> None:
        """Delete an OpenSearch internal user."""
        self._check_user_exists(username)
        self.client.transport.perform_request(
            "DELETE",
            f"/_plugins/_security/api/internalusers/{username}",
        )
        logger.info("Deleted internal user: %s", username)

    def get_internal_user(self, username: str) -> dict:
        """Get an OpenSearch internal user's details."""
        return self._check_user_exists(username)

    def list_internal_users(self) -> dict:
        """List all OpenSearch internal users."""
        return self.client.transport.perform_request(
            "GET",
            "/_plugins/_security/api/internalusers/",
        )

    def update_internal_user_password(self, username: str, password: str) -> None:
        """Update an internal user's password."""
        self._check_user_exists(username)
        self.client.transport.perform_request(
            "PATCH",
            f"/_plugins/_security/api/internalusers/{username}",
            body=[{"op": "replace", "path": "/password", "value": password}],
        )
        logger.info("Reset password for internal user: %s", username)

    def update_internal_user_attributes(
        self, username: str, attributes: dict[str, str]
    ) -> None:
        """Update an internal user's attributes."""
        self._check_user_exists(username)
        self.client.transport.perform_request(
            "PATCH",
            f"/_plugins/_security/api/internalusers/{username}",
            body=[{"op": "replace", "path": "/attributes", "value": attributes}],
        )

    # ── Role mapping helpers ──────────────────────────────────────────

    def add_user_to_role_mapping(self, role_name: str, username: str) -> None:
        """Add a user to a role mapping, creating it if necessary."""
        try:
            resp = self.client.transport.perform_request(
                "GET",
                f"/_plugins/_security/api/rolesmapping/{role_name}",
            )
            users = list(resp[role_name].get("users", []))
        except NotFoundError:
            users = []

        if username not in users:
            users.append(username)

        body = {"users": users}
        self.client.transport.perform_request(
            "PUT",
            f"/_plugins/_security/api/rolesmapping/{role_name}",
            body=body,
        )
        logger.info("Added user '%s' to role mapping '%s'", username, role_name)

    def remove_user_from_role_mapping(self, role_name: str, username: str) -> None:
        """Remove a user from a role mapping."""
        try:
            resp = self.client.transport.perform_request(
                "GET",
                f"/_plugins/_security/api/rolesmapping/{role_name}",
            )
            users = list(resp[role_name].get("users", []))
        except NotFoundError:
            return

        if username in users:
            users.remove(username)

        body = {"users": users}
        self.client.transport.perform_request(
            "PUT",
            f"/_plugins/_security/api/rolesmapping/{role_name}",
            body=body,
        )
        logger.info("Removed user '%s' from role mapping '%s'", username, role_name)

    # ── Analyst role ──────────────────────────────────────────────────

    ANALYST_ROLE = "analyst"

    def ensure_analyst_role(self) -> None:
        """Create or update the analyst role with read-only
        access to all client tenants."""
        body = {
            "cluster_permissions": [],
            "index_permissions": [
                {
                    "index_patterns": [
                        "*_dmarc_aggregate*",
                        "*_dmarc_forensic*",
                        "*_dmarc_smtp_tls*",
                    ],
                    "allowed_actions": ["read", "search", "get"],
                }
            ],
            "tenant_permissions": [
                {
                    "tenant_patterns": ["client_*"],
                    "allowed_actions": ["kibana_all_read"],
                }
            ],
        }
        self.client.transport.perform_request(
            "PUT",
            f"/_plugins/_security/api/roles/{self.ANALYST_ROLE}",
            body=body,
        )
        logger.info("Ensured analyst role exists")

    # ── User disable ─────────────────────────────────────────────────

    def disable_user(self, username: str) -> list[str]:
        """Disable a user by changing their password and removing role mappings.

        The password is set to an unknown random value, preventing login.
        Role mappings are removed so even if the user somehow authenticates,
        they have no access. To re-enable, use reset-password.
        """
        user = self.get_internal_user(username)
        attrs = user.get("attributes", {})
        roles = json.loads(attrs.get("roles", "[]"))

        # Change password to unknown random value — prevents login
        random_password = secrets.token_urlsafe(32)
        self.update_internal_user_password(username, random_password)

        for role in roles:
            self.remove_user_from_role_mapping(role, username)

        attrs["disabled"] = "true"
        self.update_internal_user_attributes(username, attrs)
        logger.info("Disabled user: %s", username)
        return roles

    def restore_user_roles(self, username: str) -> list[str]:
        """Restore role mappings for a disabled user and clear the disabled flag."""
        user = self.get_internal_user(username)
        attrs = user.get("attributes", {})
        if attrs.get("disabled") != "true":
            return []

        roles = json.loads(attrs.get("roles", "[]"))
        for role in roles:
            self.add_user_to_role_mapping(role, username)

        attrs["disabled"] = "false"
        self.update_internal_user_attributes(username, attrs)
        logger.info("Restored roles for user: %s", username)
        return roles
