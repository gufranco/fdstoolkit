from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fdstoolkit.codecs import fds
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.drive.align import good_block
from fdstoolkit.drive.captures import Bundle, Capture
from fdstoolkit.drive.vote import VoteResult, identities, vote_side
from fdstoolkit.hardware.ports import BlockRead
from fdstoolkit.hardware.session import DumpResult, SideDump


@dataclass(frozen=True, slots=True)
class Recovery:
    result: DumpResult
    recovered: tuple[tuple[int, int], ...]
    lines: tuple[str, ...]


def _as_blocks(reads: Sequence[BlockRead]) -> list[Block]:
    return [
        Block(kind=BlockKind(read.payload[0]), payload=read.payload, stored_crc=None)
        for read in reads
    ]


def _replacement(
    vote: VoteResult, reads: Sequence[BlockRead], position: int
) -> tuple[Block, bool] | None:
    wanted = identities(_as_blocks(reads))
    identity = wanted[position]
    occurrence = wanted[:position].count(identity)
    slots = [slot for slot, key in enumerate(identities(vote.side.blocks)) if key == identity]
    if occurrence >= len(slots):
        return None
    slot = slots[occurrence]
    block = vote.side.blocks[slot]
    if not good_block(block):
        return None
    return block, slot in vote.recovered


def _side(
    dumped: SideDump, captures: Sequence[bytes]
) -> tuple[SideDump, list[tuple[int, bool]], list[str]]:
    vote = vote_side(captures)
    blocks = list(dumped.blocks)
    recovered: list[tuple[int, bool]] = []
    for position in dumped.failed_blocks:
        found = _replacement(vote, dumped.blocks, position)
        if found is None:
            continue
        block, voted = found
        blocks[position] = BlockRead(
            index=position,
            payload=block.payload,
            crc_ok=True,
            attempts=len(captures),
            stored_crc=block.computed_crc,
        )
        recovered.append((position, voted))
    return SideDump(index=dumped.index, blocks=tuple(blocks)), recovered, list(vote.notes)


def _line(side: int, block: int, *, voted: bool, reads: int) -> str:
    how = f"by a pulse vote across {reads} reads" if voted else f"from one of {reads} saved reads"
    return f"  side {side} block {block}: recovered {how}"


def recover(result: DumpResult, captures: Sequence[Capture]) -> Recovery:
    sides: list[SideDump] = []
    recovered: list[tuple[int, int]] = []
    lines: list[str] = []
    for dumped in result.sides:
        if not dumped.failed_blocks:
            sides.append(dumped)
            continue
        reads = [capture.data for capture in captures if capture.side == dumped.index]
        repaired, voted, notes = _side(dumped, reads)
        sides.append(repaired)
        recovered.extend((dumped.index, block) for block, _ in voted)
        lines.extend(
            _line(dumped.index, block, voted=by_vote, reads=len(reads)) for block, by_vote in voted
        )
        lines.extend(f"  side {dumped.index} {note}" for note in notes)
    return Recovery(
        result=DumpResult(sides=tuple(sides)), recovered=tuple(recovered), lines=tuple(lines)
    )


@dataclass(frozen=True, slots=True)
class Rebuild:
    disk: Disk
    unresolved: tuple[tuple[int, int], ...]
    lines: tuple[str, ...]


def rebuild(bundle: Bundle) -> Rebuild:
    sides: list[Side] = []
    unresolved: list[tuple[int, int]] = []
    lines: list[str] = []
    for side in bundle.sides:
        vote = vote_side(bundle.of_side(side))
        sides.append(Side(blocks=vote.side.blocks, tail=b"", capacity=fds.SIDE_SIZE))
        unresolved.extend((side, block) for block in vote.unresolved)
        if vote.recovered:
            lines.append(f"  side {side}: {len(vote.recovered)} block(s) recovered by a pulse vote")
        lines.extend(f"  side {side} {note}" for note in vote.notes)
        lines.extend(f"  side {side} block {block}: never read clean" for block in vote.unresolved)
    return Rebuild(disk=Disk(sides=tuple(sides)), unresolved=tuple(unresolved), lines=tuple(lines))
