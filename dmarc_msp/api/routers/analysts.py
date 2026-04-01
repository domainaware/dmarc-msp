"""Analyst account management API routes."""

from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, HTTPException
from opensearchpy import TransportError

from dmarc_msp.api.dependencies import OpenSearchServiceDep
from dmarc_msp.api.schemas import AnalystCreate, UserCredentials, UserInfo
from dmarc_msp.services.opensearch import (
    OpenSearchService,
    UserAlreadyExistsError,
    UserNotFoundError,
)


def _handle_error(e: Exception) -> None:
    if isinstance(e, UserAlreadyExistsError):
        raise HTTPException(409, str(e))
    if isinstance(e, UserNotFoundError):
        raise HTTPException(404, str(e))
    if isinstance(e, TransportError):
        raise HTTPException(502, f"OpenSearch returned {e.status_code}: {e.error}")
    raise HTTPException(500, str(e))


router = APIRouter()

KIBANA_READ_ONLY = "kibana_read_only"


@router.post("", response_model=UserCredentials, status_code=201)
def create_analyst(body: AnalystCreate, os_svc: OpenSearchServiceDep):
    roles = [OpenSearchService.ANALYST_ROLE, KIBANA_READ_ONLY]
    password = secrets.token_urlsafe(24)

    try:
        os_svc.ensure_analyst_role()
        os_svc.create_internal_user(
            username=body.username,
            password=password,
            attributes={
                "role_type": "analyst",
                "roles": json.dumps(roles),
                "disabled": "false",
            },
            description="Analyst account",
        )
        for role in roles:
            os_svc.add_user_to_role_mapping(role, body.username)

        return UserCredentials(
            username=body.username,
            password=password,
            message=(
                "Analyst account created."
                " Save this password — it will not be shown again."
            ),
        )
    except Exception as e:
        _handle_error(e)


@router.get("", response_model=list[UserInfo])
def list_analysts(os_svc: OpenSearchServiceDep):
    users = os_svc.list_internal_users()
    result = []
    for username, data in sorted(users.items()):
        attrs = data.get("attributes", {})
        if attrs.get("role_type") != "analyst":
            continue
        result.append(
            UserInfo(
                username=username,
                role_type="analyst",
                disabled=attrs.get("disabled") == "true",
                description=data.get("description", ""),
            )
        )
    return result


@router.post("/{username}/reset-password", response_model=UserCredentials)
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


@router.post("/{username}/disable")
def disable_analyst(username: str, os_svc: OpenSearchServiceDep):
    """Disable by changing password to unknown value and removing role mappings."""
    try:
        roles = os_svc.disable_user(username)
        return {
            "message": (
                f"Disabled '{username}'."
                f" Password changed and removed from roles:"
                f" {', '.join(roles)}."
                " Use reset-password to re-enable."
            )
        }
    except Exception as e:
        _handle_error(e)


@router.delete("/{username}")
def delete_analyst(username: str, os_svc: OpenSearchServiceDep):
    try:
        user = os_svc.get_internal_user(username)
        attrs = user.get("attributes", {})
        roles = json.loads(attrs.get("roles", "[]"))
        for role in roles:
            os_svc.remove_user_from_role_mapping(role, username)
        os_svc.delete_internal_user(username)
        return {"message": f"Deleted analyst account: {username}"}
    except Exception as e:
        _handle_error(e)
