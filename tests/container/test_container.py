from __future__ import annotations

import pytest

from fdstoolkit.build.calibration import calibration_disk, calibration_image
from fdstoolkit.codecs import qd
from fdstoolkit.codecs.container import Container, decode_detected, detect_container
from fdstoolkit.core.disk import Disk

QD_SIDE = 65536
FDS_SIDE = 65500
PROBE_END = 64


def qd_image(sides: int) -> bytes:
    disk = calibration_disk()
    data, _ = qd.encode(Disk(sides=disk.sides[:sides]))
    return data


@pytest.mark.parametrize("sides", [1, 2])
def test_a_qd_image_is_recognised_by_its_side_size(sides: int) -> None:
    # Arrange
    data = qd_image(sides)

    # Act
    found = detect_container(data)

    # Assert
    assert found is Container.QD


@pytest.mark.parametrize("headered", [False, True])
def test_an_fds_image_is_recognised_with_or_without_its_header(*, headered: bool) -> None:
    # Arrange
    data = calibration_image(headered=headered)

    # Act
    found = detect_container(data)

    # Assert
    assert found is Container.FDS


def test_a_cut_short_qd_side_is_recognised_by_the_checksum_after_its_disk_info() -> None:
    # Arrange
    data = qd_image(1)[: QD_SIDE - 100]

    # Act
    found = detect_container(data)

    # Assert
    assert found is Container.QD


def test_a_cut_short_fds_side_stays_fds() -> None:
    # Arrange
    data = calibration_image(headered=False)[: FDS_SIDE - 100]

    # Act
    found = detect_container(data)

    # Assert
    assert found is Container.FDS


def test_bytes_too_short_to_probe_are_read_as_fds() -> None:
    # Arrange
    data = qd_image(1)[: PROBE_END // 2]

    # Act
    found = detect_container(data)

    # Assert
    assert found is Container.FDS


def test_a_detected_qd_decodes_to_the_disk_it_holds() -> None:
    # Arrange
    data = qd_image(1)

    # Act
    disk, _, container = decode_detected(data)

    # Assert
    assert container is Container.QD
    assert [side.file_count for side in disk.sides] == [6]
