from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Final
from urllib.parse import urlsplit

from fastapi import Request, Response
from fastapi.responses import JSONResponse

LOOPBACK_HOSTS: Final = frozenset({"127.0.0.1", "localhost", "::1"})
SAFE_METHODS: Final = frozenset({"GET", "HEAD", "OPTIONS"})
TRUSTED_FETCH_SITES: Final = frozenset({"same-origin", "none"})
BAD_HOST: Final = 400
FORBIDDEN: Final = 403
PROTECTIVE_HEADERS: Final = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=(), usb=()",
}

Middleware = Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]


def _foreign_host(request: Request, allowed: frozenset[str]) -> str | None:
    host = request.url.hostname or ""
    return None if host in allowed else request.headers.get("host", "")


def _foreign_origin(request: Request) -> str | None:
    if request.method in SAFE_METHODS:
        return None
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in TRUSTED_FETCH_SITES:
        return f"a {site} page"
    origin = request.headers.get("origin")
    if origin is None or urlsplit(origin).netloc == request.headers.get("host"):
        return None
    return origin


def _refused(status: int, detail: str) -> Response:
    return JSONResponse(status_code=status, content={"detail": detail})


def request_guard(allowed_hosts: frozenset[str]) -> Middleware:
    allowed = LOOPBACK_HOSTS | allowed_hosts

    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = _foreign_host(request, allowed)
        origin = _foreign_origin(request)
        if host is not None:
            answer = _refused(
                BAD_HOST,
                f"this server answers to {', '.join(sorted(allowed))}, not to {host}. "
                "A page that reached it under another name is refused",
            )
        elif origin is not None:
            answer = _refused(
                FORBIDDEN,
                f"a request from {origin} cannot change anything here; only this page can",
            )
        else:
            answer = await call_next(request)
        answer.headers.update(PROTECTIVE_HEADERS)
        return answer

    return guard
