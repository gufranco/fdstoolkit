from __future__ import annotations

from enum import StrEnum
from typing import Final

from fdstoolkit.codecs import fds, qd
from fdstoolkit.core.blocks import DISK_INFO_SIZE, BlockKind
from fdstoolkit.core.crc import CRC_SIZE
from fdstoolkit.core.diagnostics import Diagnostic
from fdstoolkit.core.disk import SIDE_SIZE, Disk

AMOUNT_WITHOUT_CRC: Final = DISK_INFO_SIZE
AMOUNT_AFTER_CRC: Final = DISK_INFO_SIZE + CRC_SIZE


class Container(StrEnum):
    FDS = "fds"
    QD = "qd"


def _checksummed(data: bytes) -> bool:
    if len(data) <= AMOUNT_AFTER_CRC or data[0] != BlockKind.DISK_INFO:
        return False
    return (
        data[AMOUNT_WITHOUT_CRC] != BlockKind.FILE_AMOUNT
        and data[AMOUNT_AFTER_CRC] == BlockKind.FILE_AMOUNT
    )


def detect_container(data: bytes) -> Container:
    if fds.has_header(data) or len(data) % SIDE_SIZE == 0:
        return Container.FDS
    if len(data) % qd.SIDE_SIZE == 0 or _checksummed(data):
        return Container.QD
    return Container.FDS


def decode_as(data: bytes, container: Container) -> tuple[Disk, tuple[Diagnostic, ...]]:
    return (qd.decode if container is Container.QD else fds.decode)(data)


def decode_detected(data: bytes) -> tuple[Disk, tuple[Diagnostic, ...], Container]:
    container = detect_container(data)
    disk, findings = decode_as(data, container)
    return disk, findings, container
