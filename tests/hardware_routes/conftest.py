from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from drive_double import SimulatedDrive
from fastapi.testclient import TestClient

from fdstoolkit.hardware.ports import BlockRead, FaultKind, HardwareFaultError
from fdstoolkit.ui.app import create_app

if TYPE_CHECKING:
    from fastapi import FastAPI
from hardware_routes_kit import ONE_SIDE, SETTLE, disk_of, serve


@pytest.fixture(name="app")
def app_fixture() -> FastAPI:
    return create_app()


@pytest.fixture(name="client")
def client_fixture(app: FastAPI) -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture(name="attached")
def attached_fixture(monkeypatch: pytest.MonkeyPatch) -> SimulatedDrive:
    return serve(monkeypatch, SimulatedDrive(disk_of(ONE_SIDE)))


@pytest.fixture(name="absent")
def absent_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    def opener() -> SimulatedDrive:
        message = "no FDSStick is attached"
        raise HardwareFaultError(message, kind=FaultKind.LINK)

    monkeypatch.setattr("fdstoolkit.ui.hardware_routes.open_fdsstick", opener)


@pytest.fixture(name="held")
def held_fixture(monkeypatch: pytest.MonkeyPatch) -> Iterator[threading.Event]:
    gate = threading.Event()

    class HeldDrive(SimulatedDrive):
        def read_side(self, side: int) -> Iterator[BlockRead]:
            gate.wait(SETTLE)
            return super().read_side(side)

    serve(monkeypatch, HeldDrive(disk_of(ONE_SIDE)))
    yield gate
    gate.set()
