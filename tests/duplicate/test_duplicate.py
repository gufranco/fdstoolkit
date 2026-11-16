from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Final

from drive_double import SimulatedDrive
from fakes import game_name, seeded

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds
from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.duplicate import duplicate, duplicate_lines
from fdstoolkit.hardware.ports import FaultKind, HardwareFaultError

FAKE = seeded(__name__)
GAME = game_name(FAKE)
OTHER_GAME = game_name(FAKE)
COPIES: Final = 5
BROKEN: Final = 3


def _disk(game: str) -> Disk:
    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name=game))
    return disk


class Queue(SimulatedDrive):
    def __init__(self, broken: int | None = None) -> None:
        super().__init__(_disk(OTHER_GAME))
        self.inserted = 0
        self._broken = broken

    def insert(self) -> None:
        self.inserted += 1
        self._disk = _disk(OTHER_GAME)

    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        if self.inserted == self._broken:
            message = "the stick refused the write twice inside the image"
            raise HardwareFaultError(message, kind=FaultKind.LINK)
        super().write_side(side, blocks)


def _operator(drive: Queue, asked: list[str]) -> Callable[[str], bool]:
    def answer(message: str) -> bool:
        asked.append(message)
        if message.startswith("put blank disk"):
            drive.insert()
        return True

    return answer


def test_every_copy_is_written_read_back_and_counted() -> None:
    # Arrange
    drive = Queue()
    asked: list[str] = []

    # Act
    report = duplicate(drive, drive, _disk(GAME), count=COPIES, ask=_operator(drive, asked))

    # Assert
    assert [copy.verified for copy in report.copies] == [True] * COPIES
    assert asked[0] == f"put blank disk 1 of {COPIES} in the drive, then confirm"
    assert drive.inserted == COPIES


def test_a_failed_copy_is_logged_and_the_queue_goes_on() -> None:
    # Arrange
    drive = Queue(broken=BROKEN)
    asked: list[str] = []

    # Act
    report = duplicate(drive, drive, _disk(GAME), count=COPIES, ask=_operator(drive, asked))

    # Assert
    failed = [copy for copy in report.copies if not copy.verified]
    assert [copy.number for copy in failed] == [BROKEN]
    assert failed[0].reason.startswith("the write stopped at side 0")
    assert duplicate_lines(report)[-1] == f"{COPIES - 1} of {COPIES} copies verified"


def test_a_disk_never_inserted_stops_the_queue_and_says_so() -> None:
    # Arrange
    drive = Queue()

    def answer(message: str) -> bool:
        if message == f"put blank disk 3 of {COPIES} in the drive, then confirm":
            return False
        drive.insert()
        return True

    # Act
    report = duplicate(drive, drive, _disk(GAME), count=COPIES, ask=answer)

    # Assert
    assert duplicate_lines(report)[-2:] == (
        "the queue stopped after 2 copy(ies): disk 3 was not inserted",
        f"2 of {COPIES} copies verified",
    )


def test_a_copy_that_reads_back_wrong_is_counted_as_failed() -> None:
    # Arrange
    drive = LeavesTheLastBlock()
    asked: list[str] = []

    # Act
    report = duplicate(drive, drive, _disk(GAME), count=1, ask=_operator(drive, asked))

    # Assert
    assert duplicate_lines(report) == (
        "copy 1 of 1: failed, 1 block(s) did not read back as written",
        "0 of 1 copies verified",
    )


def test_a_verified_copy_names_its_grade() -> None:
    # Arrange
    drive = Queue()
    asked: list[str] = []

    # Act
    report = duplicate(drive, drive, _disk(GAME), count=1, ask=_operator(drive, asked))

    # Assert
    assert duplicate_lines(report)[0] == "copy 1 of 1: verified, grade clean"


class LeavesTheLastBlock(Queue):
    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        current = self.disk
        assert current is not None
        kept = [block.payload for block in current.sides[side].blocks[-1:]]
        super().write_side(side, [*blocks, *kept])
