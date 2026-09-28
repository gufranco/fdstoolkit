from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Final

from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError

LOCK_PATH: Final = Path(tempfile.gettempdir()) / "fdstoolkit-fdsstick.lock"
LOCK_MODE: Final = 0o600
BUSY: Final = (
    "another fdstoolkit, on the command line or behind the web page, is using the FDSStick. "
    "Wait for it to finish, since two programs driving one drive corrupt each other's reads "
    "and writes"
)


class DriveBusyError(HardwareFaultError):
    pass


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
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, LOCK_MODE)
    except OSError as error:
        message = (
            f"cannot open the drive lock {path}: {error.strerror}. Another user on this machine "
            "may own it; remove the file once nobody is using the FDSStick"
        )
        raise HardwareFaultError(message, kind=FaultKind.LINK) from error
    if not _try_lock(descriptor):
        os.close(descriptor)
        raise DriveBusyError(BUSY, kind=FaultKind.LINK)
    return DriveLock(descriptor)
