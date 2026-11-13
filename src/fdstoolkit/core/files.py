from __future__ import annotations

from dataclasses import dataclass

from fdstoolkit.core.blocks import Block, BlockKind, FileHeader, FileKind
from fdstoolkit.core.disk import Disk, Side


@dataclass(frozen=True, slots=True)
class ExtractedFile:
    side: int
    position: int
    number: int
    file_id: int
    name: str
    address: int
    kind: FileKind
    data: bytes
    hidden: bool

    @property
    def size(self) -> int:
        return len(self.data)


def file_pairs(side: Side) -> list[tuple[int, Block, Block | None]]:
    found: list[tuple[int, Block, Block | None]] = []
    blocks = list(side.blocks)
    for index, block in enumerate(blocks):
        if block.kind is not BlockKind.FILE_HEADER:
            continue
        follower = blocks[index + 1] if index + 1 < len(blocks) else None
        data = follower if follower is not None and follower.kind is BlockKind.FILE_DATA else None
        found.append((index, block, data))
    return found


def extract_files(disk: Disk) -> tuple[ExtractedFile, ...]:
    out: list[ExtractedFile] = []
    for side_index, side in enumerate(disk.sides):
        declared = side.declared_file_count or 0
        for position, (_, header_block, data_block) in enumerate(file_pairs(side)):
            header = FileHeader.parse(header_block.payload)
            out.append(
                ExtractedFile(
                    side=side_index,
                    position=position,
                    number=header.number,
                    file_id=header.file_id,
                    name=header.name,
                    address=header.address,
                    kind=header.kind,
                    data=data_block.payload[1:] if data_block is not None else b"",
                    hidden=position >= declared,
                )
            )
    return tuple(out)
