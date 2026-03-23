"""Retention policy API routes."""

from __future__ import annotations

from fastapi import APIRouter

from dmarc_msp.api.dependencies import RetentionServiceDep

router = APIRouter()


@router.post("/ensure-default")
def ensure_default_policy(svc: RetentionServiceDep):
    svc.ensure_default_policy()
    return {"message": "Default retention policy ensured"}
