from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from fdstoolkit.codecs.raw import (
    NOMINAL_LONG,
    NOMINAL_MEDIUM,
    NOMINAL_SHORT,
    block_regions,
    encode_block_stream,
    pack_raw03,
    unpack_raw03,
)
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.drive.captures import Capture
from fdstoolkit.hardware.ports import BlockRead, DriveStatus, FaultKind, HardwareFaultError

DAMAGE_OFFSET = 40
DAMAGE_STRIDE = 7
TRAILING_GAP = 4000
NOMINAL_COUNTS = (NOMINAL_SHORT, NOMINAL_MEDIUM, NOMINAL_LONG, NOMINAL_LONG * 2)
COUNT_SCALE = 1.5
COUNT_JITTER = 3
BYTE_MAX = 255
CRC_DAMAGE = 0xFFFF


@dataclass(frozen=True, slots=True)
class FaultPlan:
    bad_crc_blocks: frozenset[int] = frozenset()
    flaky_blocks: Mapping[int, int] = field(
        default_factory=lambda: MappingProxyType({}),
    )
    unstable_blocks: frozenset[int] = frozenset()
    link_lost_after: int | None = None
    writes_do_not_stick: bool = False


def counts_of(packed: bytes) -> bytes:
    classes = unpack_raw03(packed) + bytes(TRAILING_GAP)
    offsets = hashlib.shake_256(b"counts").digest(len(classes))
    return bytes(
        min(
            BYTE_MAX,
            round(NOMINAL_COUNTS[value] * COUNT_SCALE)
            + offset % (2 * COUNT_JITTER + 1)
            - COUNT_JITTER,
        )
        for value, offset in zip(classes, offsets, strict=True)
    )


class SimulatedDrive:
    def __init__(
        self,
        disk: Disk | None,
        *,
        write_protected: bool = False,
        battery_ok: bool = True,
        ready: bool = True,
        plan: FaultPlan | None = None,
        timing_mode: int | None = None,
    ) -> None:
        self._disk = disk
        self._timing_mode = timing_mode
        self._write_protected = write_protected
        self._battery_ok = battery_ok
        self._ready = ready
        self._plan = plan or FaultPlan()
        self._attempts: dict[tuple[int, int], int] = {}
        self._reads: dict[tuple[int, int], int] = {}
        self.read_count = 0
        self.write_count = 0
        self.closed = False
        self._captures: list[Capture] = []

    def close(self) -> None:
        self.closed = True

    @property
    def captures(self) -> tuple[Capture, ...]:
        return tuple(self._captures)

    @property
    def resyncs(self) -> tuple[tuple[int, int], ...]:
        return ()

    def _capture(self, side: Side, read: int = 1) -> bytes:
        packed = encode_block_stream([block.payload for block in side.blocks])
        if not self._plan.bad_crc_blocks:
            return packed
        values = bytearray(unpack_raw03(packed))
        regions = block_regions(bytes(values))
        for index in self._plan.bad_crc_blocks:
            if index < len(regions):
                start, end = regions[index]
                span = max(end - start - 1, 1)
                spot = start + 1 + (DAMAGE_OFFSET + DAMAGE_STRIDE * read) % span
                values[spot] = 1 if values[spot] == 0 else 0
        return pack_raw03(bytes(values) + bytes(TRAILING_GAP))

    def status(self) -> DriveStatus:
        return DriveStatus(
            disk_present=self._disk is not None,
            write_protected=self._write_protected,
            battery_ok=self._battery_ok,
            ready=self._ready,
        )

    selects_sides: bool = True

    @property
    def disk(self) -> Disk | None:
        return self._disk

    def _side(self, side: int) -> Side:
        if self._disk is None:
            message = "no disk in the drive"
            raise HardwareFaultError(message, kind=FaultKind.MEDIA)
        if not 0 <= side < self._disk.side_count:
            message = f"the drive has no side {side}"
            raise HardwareFaultError(message, kind=FaultKind.MEDIA)
        return self._disk.sides[side]

    def _payload_for(self, side: int, index: int, block: Block) -> bytes:
        if index not in self._plan.unstable_blocks:
            return block.payload
        seen = self._reads.get((side, index), 0)
        self._reads[(side, index)] = seen + 1
        noise = bytes([(seen + 1) & 0xFF])
        return block.payload[:-1] + noise if len(block.payload) > 1 else block.payload + noise

    def _crc_ok_for(self, side: int, index: int) -> bool:
        if index in self._plan.bad_crc_blocks:
            return False
        needed = self._plan.flaky_blocks.get(index)
        if needed is None:
            return True
        key = (side, index)
        self._attempts[key] = self._attempts.get(key, 0) + 1
        return self._attempts[key] >= needed

    def read_side(self, side: int) -> Iterator[BlockRead]:
        target = self._side(side)
        self.read_count += 1
        read = sum(1 for capture in self._captures if capture.side == side) + 1
        self._captures.append(Capture(side=side, read=read, data=self._capture(target, read)))
        for index, block in enumerate(target.blocks):
            if self._plan.link_lost_after is not None and index >= self._plan.link_lost_after:
                message = "the device stopped answering"
                raise HardwareFaultError(message, kind=FaultKind.LINK)
            crc_ok = self._crc_ok_for(side, index)
            yield BlockRead(
                index=index,
                payload=self._payload_for(side, index, block),
                crc_ok=crc_ok,
                attempts=1,
                stored_crc=block.computed_crc if crc_ok else block.computed_crc ^ CRC_DAMAGE,
            )

    def read_raw_side(self, *, what: str, mode: int = 0) -> bytes:
        del what
        self.read_count += 1
        packed = self._capture(self._side(self._raw_side()))
        if mode and mode == self._timing_mode:
            return counts_of(packed)
        return packed

    def _raw_side(self) -> int:
        return 0

    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        target = self._side(side)
        if self._write_protected:
            message = "the disk is write protected"
            raise HardwareFaultError(message, kind=FaultKind.PROTECTED)
        if not self._battery_ok:
            message = "the battery is too low to write"
            raise HardwareFaultError(message, kind=FaultKind.MEDIA)
        self.write_count += 1
        if self._plan.writes_do_not_stick or self._disk is None:
            return
        written = Side(
            blocks=tuple(
                Block(kind=BlockKind(payload[0]), payload=payload, stored_crc=None)
                for payload in blocks
            ),
            tail=b"",
            capacity=target.capacity,
        )
        sides = list(self._disk.sides)
        sides[side] = written
        self._disk = Disk(sides=tuple(sides), header_side_count=self._disk.header_side_count)


class FacingDrive(SimulatedDrive):
    selects_sides = False

    def __init__(self, disk: Disk | None, *, plan: FaultPlan | None = None) -> None:
        super().__init__(disk, plan=plan)
        self.facing = 0
        self.turns = 0

    def turn(self, message: str) -> bool:
        del message
        self.facing ^= 1
        self.turns += 1
        return True

    def read_side(self, side: int) -> Iterator[BlockRead]:
        del side
        return super().read_side(self.facing)

    def _raw_side(self) -> int:
        return self.facing

    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        del side
        super().write_side(self.facing, blocks)
