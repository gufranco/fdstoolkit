from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


class FakeUvicorn:
    def __init__(self, order: list[str] | None = None) -> None:
        self.started: list[tuple[str, int]] = []
        self.apps: list[FastAPI] = []
        self._order = order if order is not None else []

    def run(self, app: FastAPI, *, host: str, port: int) -> None:
        self._order.append("run")
        self.apps.append(app)
        self.started.append((host, port))
