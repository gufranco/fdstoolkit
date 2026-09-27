from __future__ import annotations

import json
from typing import TYPE_CHECKING, Final

from starlette.datastructures import Headers

if TYPE_CHECKING:
    from starlette.types import ASGIApp, Message, Receive, Scope, Send

TOO_LARGE: Final = 413
CONTENT_LENGTH: Final = "content-length"


def _refusal(limit: int, carried: str) -> bytes:
    detail = (
        f"the request carries {carried} bytes, and this server accepts {limit} at most. "
        "A two-side disk image is about 131,000 bytes"
    )
    return json.dumps({"detail": detail}).encode()


def _declared(scope: Scope) -> int | None:
    value = Headers(scope=scope).get(CONTENT_LENGTH, "")
    return int(value) if value.isdigit() else None


def _replay(body: bytes, receive: Receive) -> Receive:
    delivered = False

    async def replay() -> Message:
        nonlocal delivered
        if delivered:
            return await receive()
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    return replay


class BodyLimit:
    def __init__(self, app: ASGIApp, *, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        declared = _declared(scope)
        if declared is not None and declared > self.limit:
            await self._refuse(send, str(declared))
            return
        await self._counted(scope, receive, send)

    async def _counted(self, scope: Scope, receive: Receive, send: Send) -> None:
        body = await self._read(receive)
        if body is None:
            await self._refuse(send, f"more than {self.limit}")
            return
        await self.app(scope, _replay(body, receive), send)

    async def _read(self, receive: Receive) -> bytes | None:
        parts: list[bytes] = []
        size = 0
        messages = 0
        more = True
        while more and size <= self.limit and messages <= self.limit:
            message = await receive()
            chunk = message.get("body", b"")
            part = chunk if isinstance(chunk, bytes) else b""
            parts.append(part)
            size += len(part)
            messages += 1
            more = message.get("type") == "http.request" and bool(message.get("more_body"))
        return None if more or size > self.limit else b"".join(parts)

    async def _refuse(self, send: Send, carried: str) -> None:
        body = _refusal(self.limit, carried)
        headers = [
            (b"content-type", b"application/json"),
            (CONTENT_LENGTH.encode(), str(len(body)).encode()),
        ]
        await send({"type": "http.response.start", "status": TOO_LARGE, "headers": headers})
        await send({"type": "http.response.body", "body": body})
