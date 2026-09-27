from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Final

from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError

LOCK_PATH: Final = Path(tempfile.gettempdir()) / "fdstoolkit-fdsstick.lock"
BUSY: Final = (
    "another fdstoolkit, on the command line or behind the web page, is using the FDSStick. "
    "Wait for it to finish, since two programs driving one drive corrupt each other's reads "
    "and writes"
)


def _try_lock(descriptor: int) -> bool:
    if sys.platform == "win32":  # pragma: no cover
        import msvcrt  # noqa: PLC0415

        try:
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl  # noqa: PLC0415

    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


class DriveLock:
    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor
        self.released = False

    def release(self) -> None:
        if self.released:
            return
        self.released = True
        os.close(self._descriptor)


def acquire_drive_lock(path: Path = LOCK_PATH) -> DriveLock:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    if not _try_lock(descriptor):
        os.close(descriptor)
        raise HardwareFaultError(BUSY, kind=FaultKind.LINK)
    return DriveLock(descriptor)
