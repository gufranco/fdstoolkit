from __future__ import annotations

import importlib
import os
import sys
import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final, Protocol, cast

from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError

LOCK_PATH: Final = Path(tempfile.gettempdir()) / "fdstoolkit-fdsstick.lock"
LOCK_MODE: Final = 0o600
NO_FOLLOW: Final[int] = getattr(os, "O_NOFOLLOW", 0)
BUSY: Final = (
    "another fdstoolkit, on the command line or behind the web page, is using the FDSStick. "
    "Wait for it to finish, since two programs driving one drive corrupt each other's reads "
    "and writes"
)


class DriveBusyError(HardwareFaultError):
    pass


class WindowsLocking(Protocol):
    LK_NBLCK: int

    def locking(self, fd: int, mode: int, nbytes: int, /) -> None: ...


class PosixLocking(Protocol):
    LOCK_EX: int
    LOCK_NB: int

    def flock(self, fd: int, operation: int, /) -> None: ...


def windows_lock(descriptor: int, module: object) -> None:
    msvcrt = cast("WindowsLocking", module)
    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)


def posix_lock(descriptor: int, module: object) -> None:
    fcntl = cast("PosixLocking", module)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


Locker = Callable[[int, object], None]
LOCKERS: Final[Mapping[str, tuple[str, Locker]]] = {"win32": ("msvcrt", windows_lock)}
POSIX_LOCKER: Final[tuple[str, Locker]] = ("fcntl", posix_lock)


def lock_exclusively(
    descriptor: int,
    *,
    platform: str = sys.platform,
    load: Callable[[str], object] = importlib.import_module,
) -> None:
    module, lock = LOCKERS.get(platform, POSIX_LOCKER)
    lock(descriptor, load(module))


def _try_lock(descriptor: int) -> bool:
    try:
        lock_exclusively(descriptor)
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
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | NO_FOLLOW, LOCK_MODE)
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
