from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fdstoolkit.codecs.raw import BITS_PER_BYTE, GAP_BITS, LEAD_IN_BITS
from fdstoolkit.core.blocks import (
    HEAD_BLOCKS,
    Block,
    BlockKind,
    FileHeader,
    declared_blocks,
    expected_kind,
)
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.diskinfo import VERIFICATION_STRING

SIDE_BUDGET: Final = 65 * 1024
LEAD_IN_BYTES: Final = LEAD_IN_BITS // BITS_PER_BYTE
GAP_BYTES: Final = GAP_BITS // BITS_PER_BYTE
CRC_BYTES: Final = 2
VERIFICATION_OFFSET: Final = 1


@dataclass(frozen=True, slots=True)
class FdsKeyCheck:
    refusals: tuple[str, ...]
    drops: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Loaded:
    count: int
    out_of_order: bool
    needed: int


def _verified(side: Side) -> bool:
    if not side.is_formatted:
        return False
    payload = side.blocks[0].payload
    return payload[VERIFICATION_OFFSET : VERIFICATION_OFFSET + len(VERIFICATION_STRING)] == (
        VERIFICATION_STRING
    )


def _encoded(index: int, block: Block) -> int:
    gap = LEAD_IN_BYTES if index == 0 else GAP_BYTES
    return gap + block.size + CRC_BYTES


def _loaded(side: Side) -> _Loaded:
    used = 0
    needed = sum(_encoded(index, block) for index, block in enumerate(side.blocks))
    for index, block in enumerate(side.blocks):
        if block.kind is not expected_kind(index):
            return _Loaded(count=index, out_of_order=True, needed=needed)
        used += _encoded(index, block)
        if used > SIDE_BUDGET:
            return _Loaded(count=index, out_of_order=False, needed=needed)
    return _Loaded(count=len(side.blocks), out_of_order=False, needed=needed)


def _declared(side: Side) -> int:
    amounts = [block for block in side.blocks if block.kind is BlockKind.FILE_AMOUNT]
    return declared_blocks(amounts[0].payload) if amounts else HEAD_BLOCKS


def _refusal(number: int, side: Side, loaded: _Loaded) -> str:
    files = side.declared_file_count or 0
    reason = (
        f"block {loaded.count} is out of order"
        if loaded.out_of_order
        else f"the side needs {loaded.needed} bytes with its gaps against {SIDE_BUDGET}"
    )
    return f"side {number}: FDSKey cannot hold the {files} declared files: {reason}"


def _drops(number: int, side: Side, loaded: _Loaded) -> tuple[str, ...]:
    if loaded.out_of_order:
        message = (
            f"side {number}: block {loaded.count} is out of order, so FDSKey drops it "
            "and every block after it"
        )
        return (message,)
    headers = [
        (index, FileHeader.parse(block.payload))
        for index, block in enumerate(side.blocks)
        if block.kind is BlockKind.FILE_HEADER and index + 1 >= loaded.count
    ]
    return tuple(
        f"side {number}: FDSKey has no room for hidden file "
        f"{(index - HEAD_BLOCKS) // 2}, {header.name}, and drops it"
        for index, header in headers
    )


def _tail(number: int, side: Side) -> tuple[str, ...]:
    if not side.tail.strip(b"\0"):
        return ()
    dropped = len(side.tail.rstrip(b"\0"))
    message = f"side {number}: FDSKey stops at the last file and drops the {dropped} bytes after it"
    return (message,)


def _side_check(number: int, side: Side) -> FdsKeyCheck:
    if not _verified(side):
        refusal = (
            f"side {number}: FDSKey refuses a side whose disk information lacks *NINTENDO-HVC*"
        )
        return FdsKeyCheck(refusals=(refusal,), drops=())
    loaded = _loaded(side)
    if loaded.count < _declared(side):
        return FdsKeyCheck(refusals=(_refusal(number, side, loaded),), drops=())
    dropped = _drops(number, side, loaded) if loaded.count < len(side.blocks) else ()
    return FdsKeyCheck(refusals=(), drops=(*dropped, *_tail(number, side)))


def fdskey_check(disk: Disk) -> FdsKeyCheck:
    checks = [_side_check(number, side) for number, side in enumerate(disk.sides)]
    return FdsKeyCheck(
        refusals=tuple(refusal for check in checks for refusal in check.refusals),
        drops=tuple(drop for check in checks for drop in check.drops),
    )
