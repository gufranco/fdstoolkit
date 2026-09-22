from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Final

from fdstk.core.crc import block_crc

DISK_INFO_SIZE: Final = 56
FILE_AMOUNT_SIZE: Final = 2
FILE_HEADER_SIZE: Final = 16
FILE_NAME_OFFSET: Final = 0x03
FILE_NAME_SIZE: Final = 8
FILE_ADDRESS_OFFSET: Final = 0x0B
FILE_SIZE_OFFSET: Final = 0x0D
FILE_KIND_OFFSET: Final = 0x0F


class BlockKind(IntEnum):
    DISK_INFO = 1
    FILE_AMOUNT = 2
    FILE_HEADER = 3
    FILE_DATA = 4


class CrcStatus(StrEnum):
    ABSENT = "absent"
    VALID = "valid"
    NULL = "null"
    MISMATCH = "mismatch"


class FileKind(IntEnum):
    PROGRAM = 0
    CHARACTER = 1
    NAMETABLE = 2
    UNKNOWN = -1


FIXED_SIZES: Final[dict[BlockKind, int]] = {
    BlockKind.DISK_INFO: DISK_INFO_SIZE,
    BlockKind.FILE_AMOUNT: FILE_AMOUNT_SIZE,
    BlockKind.FILE_HEADER: FILE_HEADER_SIZE,
}


@dataclass(frozen=True, slots=True)
class Block:
    kind: BlockKind
    payload: bytes
    stored_crc: int | None = None

    def __post_init__(self) -> None:
        if not self.payload:
            message = f"a {self.kind.name} block cannot have an empty payload"
            raise ValueError(message)
        if self.payload[0] != int(self.kind):
            message = (
                f"a {self.kind.name} block must start with kind byte "
                f"{int(self.kind):#04x}, got {self.payload[0]:#04x}"
            )
            raise ValueError(message)
        expected = FIXED_SIZES.get(self.kind)
        if expected is not None and len(self.payload) != expected:
            message = f"a {self.kind.name} block is {expected} bytes, got {len(self.payload)}"
            raise ValueError(message)

    @property
    def size(self) -> int:
        return len(self.payload)

    @property
    def computed_crc(self) -> int:
        return block_crc(self.payload)

    @property
    def crc_status(self) -> CrcStatus:
        if self.stored_crc is None:
            return CrcStatus.ABSENT
        if self.stored_crc == 0:
            return CrcStatus.NULL
        if self.stored_crc == self.computed_crc:
            return CrcStatus.VALID
        return CrcStatus.MISMATCH

    def with_computed_crc(self) -> Block:
        return Block(kind=self.kind, payload=self.payload, stored_crc=self.computed_crc)

    def with_null_crc(self) -> Block:
        return Block(kind=self.kind, payload=self.payload, stored_crc=0)

    def without_crc(self) -> Block:
        return Block(kind=self.kind, payload=self.payload, stored_crc=None)


@dataclass(frozen=True, slots=True)
class FileHeader:
    number: int
    file_id: int
    raw_name: bytes
    address: int
    size: int
    raw_kind: int

    @classmethod
    def parse(cls, payload: bytes) -> FileHeader:
        if len(payload) != FILE_HEADER_SIZE:
            message = f"a file header is {FILE_HEADER_SIZE} bytes, got {len(payload)}"
            raise ValueError(message)
        return cls(
            number=payload[1],
            file_id=payload[2],
            raw_name=payload[FILE_NAME_OFFSET : FILE_NAME_OFFSET + FILE_NAME_SIZE],
            address=int.from_bytes(
                payload[FILE_ADDRESS_OFFSET : FILE_ADDRESS_OFFSET + 2], "little"
            ),
            size=int.from_bytes(payload[FILE_SIZE_OFFSET : FILE_SIZE_OFFSET + 2], "little"),
            raw_kind=payload[FILE_KIND_OFFSET],
        )

    @property
    def name(self) -> str:
        return self.raw_name.decode("ascii", errors="replace").rstrip(" \0")

    @property
    def kind(self) -> FileKind:
        try:
            return FileKind(self.raw_kind)
        except ValueError:
            return FileKind.UNKNOWN
