from __future__ import annotations

from pathlib import Path

import pytest

from fdstoolkit.hardware.device_lock import (
    acquire_drive_lock,
    lock_exclusively,
    posix_lock,
    windows_lock,
)
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError


def test_a_second_holder_is_refused_while_the_first_holds_the_drive(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "drive.lock"
    first = acquire_drive_lock(path)

    # Act
    with pytest.raises(HardwareFaultError, match="another fdstoolkit") as refused:
        acquire_drive_lock(path)

    # Assert
    first.release()
    assert refused.value.kind is FaultKind.LINK


def test_the_drive_can_be_taken_again_once_released(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "drive.lock"
    acquire_drive_lock(path).release()
    again = acquire_drive_lock(path)

    # Act
    again.release()

    # Assert
    assert path.exists()


def test_releasing_twice_is_harmless(tmp_path: Path) -> None:
    # Arrange
    held = acquire_drive_lock(tmp_path / "drive.lock")
    held.release()

    # Act
    held.release()

    # Assert
    assert held.released


def test_a_lock_file_this_user_cannot_open_is_a_hardware_fault(tmp_path: Path) -> None:
    # Arrange
    path = tmp_path / "drive.lock"
    path.write_bytes(b"")
    path.chmod(0)

    # Act
    with pytest.raises(HardwareFaultError, match="cannot open the drive lock") as refused:
        acquire_drive_lock(path)

    # Assert
    path.chmod(0o600)
    assert str(path) in str(refused.value)


class RecordingLocks:
    LK_NBLCK = 2
    LOCK_EX = 2
    LOCK_NB = 4

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[int, ...]]] = []

    def locking(self, fd: int, mode: int, nbytes: int, /) -> None:
        self.calls.append(("locking", (fd, mode, nbytes)))

    def flock(self, fd: int, operation: int, /) -> None:
        self.calls.append(("flock", (fd, operation)))


def test_windows_takes_the_first_byte_without_waiting() -> None:
    # Arrange
    module = RecordingLocks()

    # Act
    windows_lock(7, module)

    # Assert
    assert module.calls == [("locking", (7, RecordingLocks.LK_NBLCK, 1))]


def test_posix_takes_an_exclusive_lock_without_waiting() -> None:
    # Arrange
    module = RecordingLocks()

    # Act
    posix_lock(7, module)

    # Assert
    assert module.calls == [("flock", (7, RecordingLocks.LOCK_EX | RecordingLocks.LOCK_NB))]


@pytest.mark.parametrize(
    ("platform", "module", "call"),
    [("win32", "msvcrt", "locking"), ("darwin", "fcntl", "flock"), ("linux", "fcntl", "flock")],
)
def test_each_platform_locks_through_its_own_module(platform: str, module: str, call: str) -> None:
    # Arrange
    recording = RecordingLocks()
    loaded: list[str] = []

    def load(name: str) -> object:
        loaded.append(name)
        return recording

    # Act
    lock_exclusively(7, platform=platform, load=load)

    # Assert
    assert loaded == [module]
    assert [name for name, _ in recording.calls] == [call]
