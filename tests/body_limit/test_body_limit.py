from __future__ import annotations

import asyncio
import base64
import json
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.build.blank import blank_image
from fdstoolkit.ui.app import MAX_BODY_BYTES, create_app
from fdstoolkit.ui.body_limit import TOO_LARGE, BodyLimit

if TYPE_CHECKING:
    from collections.abc import Iterator

    from starlette.types import Message, Receive, Scope, Send

CHUNK = 1024 * 1024
OK = 200


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app())


def chunks(count: int) -> Iterator[bytes]:
    return (b" " * CHUNK for _ in range(count))


def test_a_chunked_body_past_the_ceiling_is_refused(client: TestClient) -> None:
    answer = client.post(
        "/api/verify",
        content=chunks(MAX_BODY_BYTES // CHUNK + 1),
        headers={"content-type": "application/json"},
    )

    assert answer.status_code == TOO_LARGE
    assert "accepts" in answer.json()["detail"]


def test_a_chunked_body_inside_the_ceiling_is_read(client: TestClient) -> None:
    image = base64.b64encode(blank_image(sides=1, headered=False, formatted=True)).decode()
    payload = json.dumps({"data": image}).encode()
    half = len(payload) // 2

    answer = client.post(
        "/api/verify",
        content=iter([payload[:half], payload[half:]]),
        headers={"content-type": "application/json"},
    )

    assert answer.status_code == OK


class Recorder:
    def __init__(self) -> None:
        self.scopes: list[str] = []
        self.messages: list[Message] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.scopes.append(str(scope["type"]))
        self.messages.append(await receive())
        self.messages.append(await receive())
        del send


def incoming(*messages: Message) -> Receive:
    queue = iter(messages)

    async def receive() -> Message:
        return next(queue)

    return receive


async def ignore(message: Message) -> None:
    del message


def test_a_scope_that_is_not_http_passes_through_untouched() -> None:
    inner = Recorder()
    startup: Message = {"type": "lifespan.startup"}
    shutdown: Message = {"type": "lifespan.shutdown"}

    asyncio.run(
        BodyLimit(inner, limit=1)({"type": "lifespan"}, incoming(startup, shutdown), ignore)
    )

    assert inner.scopes == ["lifespan"]
    assert inner.messages == [startup, shutdown]


def test_after_the_body_the_app_hears_the_client_directly() -> None:
    inner = Recorder()
    gone: Message = {"type": "http.disconnect"}
    request: Message = {"type": "http.request", "body": b"{}", "more_body": False}

    asyncio.run(
        BodyLimit(inner, limit=CHUNK)(
            {"type": "http", "headers": []}, incoming(request, gone), ignore
        )
    )

    assert inner.messages == [request, gone]
