"""parsedmarc reload API route."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from dmarc_msp.api.dependencies import SettingsDep
from dmarc_msp.process.docker import DockerSignaler

router = APIRouter()


@router.post("/reload")
def reload_parsedmarc(settings: SettingsDep):
    signaler = DockerSignaler(settings.parsedmarc.container)
    if signaler.send_sighup():
        return {"message": "parsedmarc reloaded"}
    raise HTTPException(500, "Failed to reload parsedmarc")
