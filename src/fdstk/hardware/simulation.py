from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType

from fdstk.core.blocks import Block, BlockKind
from fdstk.core.disk import Disk, Side
from fdstk.hardware.ports import BlockRead, DriveStatus, FaultKind, HardwareFaultError


@dataclass(frozen=True, slots=True)
class FaultPlan:
    bad_crc_blocks: frozenset[int] = frozenset()
    flaky_blocks: Mapping[int, int] = field(
        default_factory=lambda: MappingProxyType({}),
    )
    unstable_blocks: frozenset[int] = frozenset()
    link_lost_after: int | None = None
    writes_do_not_stick: bool = False


class SimulatedDrive:
    def __init__(
        self,
        disk: Disk | None,
        *,
        write_protected: bool = False,
        battery_ok: bool = True,
        ready: bool = True,
        plan: FaultPlan | None = None,
    ) -> None:
        self._disk = disk
        self._write_protected = write_protected
        self._battery_ok = battery_ok
        self._ready = ready
        self._plan = plan or FaultPlan()
        self._attempts: dict[tuple[int, int], int] = {}
        self._reads: dict[tuple[int, int], int] = {}
        self.read_count = 0
        self.write_count = 0

    def status(self) -> DriveStatus:
        return DriveStatus(
            disk_present=self._disk is not None,
            write_protected=self._write_protected,
            battery_ok=self._battery_ok,
            ready=self._ready,
        )

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
        for index, block in enumerate(target.blocks):
            if self._plan.link_lost_after is not None and index >= self._plan.link_lost_after:
                message = "the device stopped answering"
                raise HardwareFaultError(message, kind=FaultKind.LINK)
            yield BlockRead(
                index=index,
                payload=self._payload_for(side, index, block),
                crc_ok=self._crc_ok_for(side, index),
                attempts=1,
            )

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
