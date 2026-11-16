from __future__ import annotations

import base64
import threading
from typing import TYPE_CHECKING

from drive_double import SimulatedDrive
from json_view import Json
from pydantic import BaseModel

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import LARGEST_FACTORY_SIDE
from fdstoolkit.codecs.fds import decode, encode
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk
from fdstoolkit.edit.files import FileSpec, insert_file

if TYPE_CHECKING:
    from collections.abc import Sequence

    import pytest
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
from fakes import game_name, seeded

FAKE = seeded(__name__)
GAME = game_name(FAKE)
OTHER_GAME = game_name(FAKE)


OK = 200


BAD_REQUEST = 400


NOT_FOUND = 404


CONFLICT = 409


UNPROCESSABLE = 422


SETTLE = 5.0


ONE_SIDE = blank_image(sides=1, headered=False, formatted=True, game_name=GAME)


TWO_SIDE = blank_image(sides=2, headered=False, formatted=True, game_name=GAME)


OTHER_TWO = blank_image(sides=2, headered=False, formatted=True, game_name=OTHER_GAME)


ONE = base64.b64encode(ONE_SIDE).decode("ascii")


TWO = base64.b64encode(TWO_SIDE).decode("ascii")


OTHER = base64.b64encode(OTHER_TWO).decode("ascii")


def disk_of(image: bytes) -> Disk:
    disk, _ = decode(image)
    return disk


def serve[D: SimulatedDrive](monkeypatch: pytest.MonkeyPatch, drive: D) -> D:
    monkeypatch.setattr("fdstoolkit.ui.hardware_routes.open_fdsstick", lambda: drive)
    return drive


def run(app: FastAPI, client: TestClient, route: str, payload: dict[str, object]) -> Json:
    started = client.post(route, json=payload)
    assert started.status_code == OK, started.text
    job_id = started.json()["id"]
    assert app.state.jobs.wait(job_id, SETTLE)
    return Json(client.get(f"/api/jobs/{job_id}").json())


def long_image() -> str:
    disk = insert_file(
        disk_of(ONE_SIDE),
        side=0,
        spec=FileSpec(
            name="LONG", address=0x6000, kind=FileKind.PROGRAM, data=bytes(LARGEST_FACTORY_SIDE)
        ),
    )
    data, _ = encode(disk, headered=False)
    return base64.b64encode(data).decode("ascii")


class Nothing(BaseModel):
    pass


class SlowReads(SimulatedDrive):
    def __init__(self, disk: Disk, gate: threading.Event) -> None:
        super().__init__(disk)
        self.gate = gate

    def read_raw_side(self, *, what: str, mode: int = 0) -> bytes:
        self.gate.wait(SETTLE)
        return super().read_raw_side(what=what, mode=mode)


class FirstWriteHeld(SimulatedDrive):
    def __init__(self, disk: Disk) -> None:
        super().__init__(disk)
        self.writing = threading.Event()
        self.release = threading.Event()

    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        first = not self.writing.is_set()
        self.writing.set()
        if first:
            self.release.wait(SETTLE)
        super().write_side(side, blocks)
