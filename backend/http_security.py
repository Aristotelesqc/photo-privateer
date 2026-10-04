"""HTTP authority boundary for the local desktop server."""
from __future__ import annotations

import ipaddress
import re

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

_AUTHORITY = re.compile(
    r"(?P<host>localhost|[0-9.]+|\[[0-9a-f:]+\])(?::(?P<port>[0-9]{1,5}))?",
    re.IGNORECASE | re.ASCII,
)


def is_loopback_authority(authority: str) -> bool:
    """Accept localhost, IPv4 loopback and bracketed ::1 with an optional port."""
    match = _AUTHORITY.fullmatch(authority)
    if match is None:
        return False
    port = match.group("port")
    if port is not None and not 1 <= int(port) <= 65535:
        return False
    host = match.group("host")
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


class LoopbackHostMiddleware:
    """Reject untrusted/malformed Host before routing or CORS responses.

    Raw headers preserve duplicates. Forwarded headers never influence this
    boundary, and synthetic test hosts have no production allowance.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in {"http", "websocket"}:
            hosts = [value for key, value in scope["headers"] if key.lower() == b"host"]
            if len(hosts) != 1 or not is_loopback_authority(hosts[0].decode("latin-1")):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await JSONResponse(
                        {"detail": "Forbidden Host. Only local loopback authorities are permitted."},
                        status_code=403,
                    )(scope, receive, send)
                return
        await self.app(scope, receive, send)
