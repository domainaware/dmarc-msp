"""Client user account management API routes."""

from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, HTTPException
from opensearchpy import TransportError

from dmarc_msp.api.dependencies import ClientServiceDep, OpenSearchServiceDep
from dmarc_msp.api.schemas import ClientUserCreate, UserCredentials, UserInfo
from dmarc_msp.services.clients import ClientNotFoundError
from dmarc_msp.services.opensearch import UserNotFoundError


def _handle_error(e: Exception) -> None:
    if isinstance(e, UserNotFoundError):
        raise HTTPException(404, str(e))
    if isinstance(e, ClientNotFoundError):
        raise HTTPException(404, str(e))
    if isinstance(e, TransportError):
        raise HTTPException(502, f"OpenSearch returned {e.status_code}: {e.error}")
    raise HTTPException(500, str(e))


router = APIRouter()

KIBANA_READ_ONLY = "kibana_read_only"


@router.post(
    "/clients/{client_name}/users",
    response_model=UserCredentials,
    status_code=201,
)
def create_client_user(
    client_name: str,
    body: ClientUserCreate,
    client_svc: ClientServiceDep,
    os_svc: OpenSearchServiceDep,
):
    try:
        client = client_svc.get(client_name)
    except ClientNotFoundError as e:
        raise HTTPException(404, str(e))

    roles = [client.tenant_name, KIBANA_READ_ONLY]
    password = secrets.token_urlsafe(24)

    try:
        os_svc.create_internal_user(
            username=body.username,
            password=password,
            attributes={
                "role_type": "client",
                "client_tenant": client.tenant_name,
                "roles": json.dumps(roles),
                "disabled": "false",
            },
            description=f"Client user for {client.name}",
        )
        for role in roles:
            os_svc.add_user_to_role_mapping(role, body.username)

        return UserCredentials(
            username=body.username,
            password=password,
            message=f"Client user created for {client.name}. Save this password — it will not be shown again.",
        )
    except Exception as e:
        _handle_error(e)


@router.get("/clients/{client_name}/users", response_model=list[UserInfo])
def list_client_users(
    client_name: str,
    client_svc: ClientServiceDep,
    os_svc: OpenSearchServiceDep,
):
    try:
        client = client_svc.get(client_name)
    except ClientNotFoundError as e:
        raise HTTPException(404, str(e))

    users = os_svc.list_internal_users()
    result = []
    for username, data in sorted(users.items()):
        attrs = data.get("attributes", {})
        if attrs.get("role_type") != "client":
            continue
        if attrs.get("client_tenant") != client.tenant_name:
            continue
        result.append(
            UserInfo(
                username=username,
                role_type="client",
                client_tenant=attrs.get("client_tenant"),
                disabled=attrs.get("disabled") == "true",
                description=data.get("description", ""),
            )
        )
    return result


@router.post("/users/{username}/reset-password", response_model=UserCredentials)
def reset_password(username: str, os_svc: OpenSearchServiceDep):
    password = secrets.token_urlsafe(24)
    try:
        os_svc.update_internal_user_password(username, password)
        restored = os_svc.restore_user_roles(username)
        msg = "Password reset."
        if restored:
            msg += f" Account re-enabled, restored roles: {', '.join(restored)}."
        msg += " Save this password — it will not be shown again."
        return UserCredentials(username=username, password=password, message=msg)
    except Exception as e:
        _handle_error(e)


@router.post("/users/{username}/disable")
def disable_user(username: str, os_svc: OpenSearchServiceDep):
    """Disable by changing password to unknown value and removing role mappings."""
    try:
        roles = os_svc.disable_user(username)
        return {
            "message": f"Disabled '{username}'. Password changed and removed from roles: {', '.join(roles)}. Use reset-password to re-enable."
        }
    except Exception as e:
        _handle_error(e)


@router.delete("/users/{username}")
def delete_user(username: str, os_svc: OpenSearchServiceDep):
    try:
        user = os_svc.get_internal_user(username)
        attrs = user.get("attributes", {})
        roles = json.loads(attrs.get("roles", "[]"))
        for role in roles:
            os_svc.remove_user_from_role_mapping(role, username)
        os_svc.delete_internal_user(username)
        return {"message": f"Deleted client user: {username}"}
    except Exception as e:
        _handle_error(e)
