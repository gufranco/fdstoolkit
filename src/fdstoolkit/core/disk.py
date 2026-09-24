from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fdstoolkit.core.blocks import Block, BlockKind, FileHeader
from fdstoolkit.core.diskinfo import DiskInfo

SIDES_PER_DISK: Final = 2


class TooManySidesError(ValueError):
    pass


def require_readable_sides(sides: int) -> None:
    if not 1 <= sides <= SIDES_PER_DISK:
        message = (
            f"a disk has {SIDES_PER_DISK} faces, so a read covers 1 or {SIDES_PER_DISK} "
            f"sides, not {sides}"
        )
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class Side:
    blocks: tuple[Block, ...]
    tail: bytes
    capacity: int

    @property
    def is_formatted(self) -> bool:
        return bool(self.blocks) and self.blocks[0].kind is BlockKind.DISK_INFO

    @property
    def disk_info(self) -> DiskInfo | None:
        if not self.is_formatted:
            return None
        return DiskInfo.parse(self.blocks[0].payload)

    @property
    def declared_file_count(self) -> int | None:
        for block in self.blocks:
            if block.kind is BlockKind.FILE_AMOUNT:
                return block.payload[1]
        return None

    @property
    def file_headers(self) -> tuple[FileHeader, ...]:
        return tuple(
            FileHeader.parse(block.payload)
            for block in self.blocks
            if block.kind is BlockKind.FILE_HEADER
        )

    @property
    def file_count(self) -> int:
        return sum(1 for block in self.blocks if block.kind is BlockKind.FILE_DATA)

    @property
    def hidden_file_count(self) -> int:
        declared = self.declared_file_count
        if declared is None:
            return 0
        return max(0, self.file_count - declared)

    @property
    def content_size(self) -> int:
        return sum(block.size for block in self.blocks)

    @property
    def has_data_after_last_block(self) -> bool:
        return bool(self.tail.strip(b"\0"))


@dataclass(frozen=True, slots=True)
class Disk:
    sides: tuple[Side, ...]
    header_side_count: int | None = None

    def __post_init__(self) -> None:
        if len(self.sides) > SIDES_PER_DISK:
            message = (
                f"this image holds {len(self.sides)} sides, but a disk has at most "
                f"{SIDES_PER_DISK} and no game uses more than one disk, so the file "
                "bundles several disks together. fdstoolkit reads one disk per image"
            )
            raise TooManySidesError(message)
        if self.header_side_count is not None and self.header_side_count != len(self.sides):
            message = (
                f"header declares {self.header_side_count} sides "
                f"but the image holds {len(self.sides)}"
            )
            raise ValueError(message)

    @property
    def side_count(self) -> int:
        return len(self.sides)
