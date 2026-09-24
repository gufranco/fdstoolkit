from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "support"))

from drive_double import SimulatedDrive

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.ui.app import create_app

HOST = "127.0.0.1"
PORT = int(os.environ.get("FDSTOOLKIT_E2E_PORT", "8765"))


class TurnedByTheOperator(SimulatedDrive):
    selects_sides = False


def two_sided_drive() -> TurnedByTheOperator:
    disk, _ = decode(blank_image(sides=2, headered=False, formatted=True, game_name="E2E"))
    return TurnedByTheOperator(disk)


def main() -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("fdstoolkit.ui.hardware_routes.open_fdsstick", two_sided_drive)
        uvicorn.run(create_app(), host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
