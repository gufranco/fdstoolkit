from __future__ import annotations

from collections.abc import Iterator, Sequence

from drive_double import FaultPlan, SimulatedDrive

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import LARGEST_FACTORY_SIDE
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk
from fdstoolkit.edit.files import FileSpec, insert_file
from fdstoolkit.hardware.ports import BlockRead


def sample_disk(sides: int = 1) -> Disk:
    disk, _ = decode(blank_image(sides=sides, headered=False, formatted=True, game_name="SMB"))
    return disk


FILES = 5


def disk_with_files(count: int = FILES) -> Disk:
    disk = sample_disk()
    for number in range(count):
        disk = insert_file(
            disk,
            side=0,
            spec=FileSpec(
                name=f"FILE{number}",
                address=0x6000,
                kind=FileKind.PROGRAM,
                data=bytes([number + 1]) * 16,
            ),
        )
    return disk


class DroppingDrive(SimulatedDrive):
    def __init__(self, disk: Disk, *, dropped: int, plan: FaultPlan) -> None:
        super().__init__(disk, plan=plan)
        self.dropped = dropped

    def read_side(self, side: int) -> Iterator[BlockRead]:
        blocks = list(super().read_side(side))
        if self.read_count == 1:
            return iter(blocks)
        return iter(blocks[: self.dropped] + blocks[self.dropped + 1 :])


class ShortFirstReadDrive(SimulatedDrive):
    def __init__(self, disk: Disk, *, kept: int) -> None:
        super().__init__(disk)
        self.kept = kept

    def read_side(self, side: int) -> Iterator[BlockRead]:
        blocks = list(super().read_side(side))
        if self.read_count == 1:
            return iter(blocks[: self.kept])
        return iter(blocks)


def longer_than_any_factory_side() -> Disk:
    disk = sample_disk()
    return insert_file(
        disk,
        side=0,
        spec=FileSpec(
            name="LONG",
            address=0x6000,
            kind=FileKind.PROGRAM,
            data=bytes(LARGEST_FACTORY_SIDE),
        ),
    )


class HeaderLockedDrive(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        kept = self._side(side).blocks[0].payload
        super().write_side(side, [kept, *blocks[1:]])


class OverlayDrive(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        current = self._side(side)
        kept = [block.payload for block in current.blocks[len(blocks) :]]
        super().write_side(side, [*blocks, *kept])


def two_sided_game() -> Disk:
    disk, _ = decode(blank_image(sides=2, headered=False, formatted=True, game_name="ZEL"))
    return disk


def blank_scratch() -> Disk:
    disk, _ = decode(blank_image(sides=2, headered=False, formatted=False))
    return disk


def other_game() -> Disk:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name="ZEL"))
    return disk


class OneFace:
    selects_sides = False

    def __init__(self, disk: Disk) -> None:
        self._inner = SimulatedDrive(disk)
        self.facing = 0

    def status(self):  # noqa: ANN201
        return self._inner.status()

    def read_side(self, side: int):  # noqa: ANN201
        del side
        return self._inner.read_side(self.facing)


class MiddleLostDrive(SimulatedDrive):
    def read_side(self, side: int) -> Iterator[BlockRead]:
        blocks = list(super().read_side(side))
        if self.read_count == 1:
            return iter(blocks[:3] + blocks[5:])
        return iter(blocks)
