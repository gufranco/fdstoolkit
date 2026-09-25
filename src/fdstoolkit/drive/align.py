from __future__ import annotations

from collections.abc import Sequence

from fdstoolkit.core.blocks import Block

Placement = tuple[bool, int | None]


def good_block(block: Block) -> bool:
    return block.stored_crc == block.computed_crc


def align_blocks(wanted: Sequence[Block], found: Sequence[Block]) -> list[Placement]:
    placed: list[Placement] = []
    cursor = 0
    for block in wanted:
        match = next(
            (
                index
                for index in range(cursor, len(found))
                if good_block(found[index]) and found[index].payload == block.payload
            ),
            None,
        )
        if match is not None:
            placed.append((True, match))
            cursor = match + 1
        elif (
            cursor < len(found)
            and not good_block(found[cursor])
            and found[cursor].kind is block.kind
        ):
            placed.append((False, cursor))
            cursor += 1
        else:
            placed.append((False, None))
    return placed
