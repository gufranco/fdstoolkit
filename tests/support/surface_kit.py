from __future__ import annotations

from collections.abc import Iterator, Sequence

from drive_double import FaultPlan, SimulatedDrive
from fakes import game_name, seeded

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.codecs.raw import class_histogram, encode_era_b
from fdstoolkit.core.blocks import BlockKind
from fdstoolkit.core.crc import block_crc, encode_crc
from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.ports import BlockRead
from fdstoolkit.hardware.session import Grade
from fdstoolkit.quality.surface import PatternPass, SurfaceReport
from fdstoolkit.quality.surface_disks import PATTERNS, SurfacePattern, pattern_disk

FAKE = seeded(__name__)
GAME = game_name(FAKE)

BLANK_BLOCKS = 2


KEY = bytes(range(16))


OTHER_KEY = bytes(range(1, 17))


DOMINANT = 0.99


MIXED_SHARE = 0.1


class FinishNoisyDrive(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        super().write_side(side, blocks)
        if self.write_count > len(PATTERNS):
            self._plan = FaultPlan(unstable_blocks=frozenset({1}))


class FinishRefusingDrive(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        if self.write_count >= len(PATTERNS):
            self.write_count += 1
            return
        super().write_side(side, blocks)


def scratch_disk():  # noqa: ANN201
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    return disk


def shares(payload: bytes) -> tuple[float, float, float]:
    framed = bytes([0x80]) + payload + encode_crc(block_crc(payload))
    counts = class_histogram(encode_era_b(framed))
    total = counts[0] + counts[1] + counts[2]
    return counts[0] / total, counts[1] / total, counts[2] / total


def data_of(pattern: SurfacePattern, key: bytes = KEY) -> bytes:
    side = pattern_disk(pattern, sides=1, key=key).sides[0]
    return b"".join(b.payload for b in side.blocks if b.kind is BlockKind.FILE_DATA)


def two_sided_scratch():  # noqa: ANN201
    disk, _ = decode(blank_image(sides=2, headered=False, formatted=True, game_name=GAME))
    return disk


class HeaderLockedDrive(SimulatedDrive):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        kept = self._side(side).blocks[0].payload
        super().write_side(side, [kept, *blocks[1:]])


class StopsAfterReads(SimulatedDrive):
    def __init__(self, disk: Disk, *, reads: int, stop: BaseException) -> None:
        super().__init__(disk)
        self.limit = reads
        self.stop = stop

    def read_side(self, side: int) -> Iterator[BlockRead]:
        if self.read_count >= self.limit:
            raise self.stop
        return super().read_side(side)


def failing(blocks: tuple[int, ...], per_side: int) -> SurfaceReport:
    return SurfaceReport(
        passes=(
            PatternPass(
                SurfacePattern.SHORT,
                verified=False,
                mismatched_blocks=tuple((0, block) for block in blocks),
                grade=Grade.FAILED,
            ),
        ),
        blocks_per_side=per_side,
    )
