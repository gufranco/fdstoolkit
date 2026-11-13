from __future__ import annotations

from pathlib import Path

import pytest

from fdstoolkit.hardware.device_lock import acquire_drive_lock
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
