"""IP allowlist middleware."""

from __future__ import annotations

import ipaddress
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


class IPAllowlistMiddleware(BaseHTTPMiddleware):
    """Restrict API access to a list of allowed source IPs."""

    def __init__(self, app, allowed_ips: list[str] | None = None):
        super().__init__(app)
        self.allowed_networks = []
        for ip_str in allowed_ips or []:
            try:
                self.allowed_networks.append(ipaddress.ip_network(ip_str, strict=False))
            except ValueError:
                logger.warning("Invalid IP/network in allowlist: %s", ip_str)

    async def dispatch(self, request: Request, call_next):
        if not self.allowed_networks:
            return await call_next(request)

        client_ip = request.client.host if request.client else None
        if client_ip:
            try:
                addr = ipaddress.ip_address(client_ip)
                if any(addr in net for net in self.allowed_networks):
                    return await call_next(request)
            except ValueError:
                pass

        logger.warning("Blocked request from %s", client_ip)
        return JSONResponse(
            status_code=403,
            content={"detail": "Access denied"},
        )
