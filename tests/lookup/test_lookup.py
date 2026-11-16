from __future__ import annotations

from dataclasses import replace

import pytest
from fakes import game_name, seeded

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.history.entries import disk_key
from fdstoolkit.history.logbook import Entry, EntryKind, record
from fdstoolkit.history.lookup import (
    BOTH,
    NEITHER,
    NO_IDENTITY,
    Subject,
    log_payload,
    look_up,
    subject_for,
)

FAKE = seeded(__name__)
GAME = game_name(FAKE)


def _disk() -> Disk:
    disk, _ = fds.decode(blank_image(sides=1, headered=False, formatted=True, game_name=GAME))
    return disk


def _logged(disk: str | None, drive: str | None) -> Entry:
    return Entry(
        run=FAKE.uuid4(),
        recorded="2026-11-01T10:00:00Z",
        kind=EntryKind.DUMP,
        disk=disk,
        title=GAME,
        stick=None,
        drive=drive,
        grade="clean",
        weak=((0, 3),),
    )


def test_a_disk_subject_is_named_by_its_identity_and_title() -> None:
    # Arrange
    disk = _disk()
    key = disk_key(disk)

    # Act
    subject = subject_for(disk, None)

    # Assert
    assert key is not None
    assert subject == Subject(disk=key.id, drive=None, title=f"{key.id} {GAME}")


def test_a_drive_subject_is_named_by_its_label() -> None:
    # Arrange
    label = "hvc-022"

    # Act
    subject = subject_for(None, label)

    # Assert
    assert subject == Subject(disk=None, drive=label, title="drive hvc-022")


@pytest.mark.parametrize(
    ("with_disk", "drive", "message"),
    [(False, None, NEITHER), (False, "", NEITHER), (True, "hvc-022", BOTH)],
)
def test_a_subject_needs_exactly_one_of_a_disk_or_a_drive(
    *, with_disk: bool, drive: str | None, message: str
) -> None:
    # Arrange
    disk = _disk() if with_disk else None

    # Act
    with pytest.raises(ValueError, match=message) as raised:
        subject_for(disk, drive)

    # Assert
    assert str(raised.value) == message


def test_an_image_without_disk_information_has_no_history() -> None:
    # Arrange
    disk = Disk(sides=(Side(blocks=(), tail=b"", capacity=0),))

    # Act
    with pytest.raises(ValueError, match="cannot know it") as raised:
        subject_for(disk, None)

    # Assert
    assert str(raised.value) == NO_IDENTITY


def test_a_disk_is_looked_up_in_the_logbook() -> None:
    # Arrange
    subject = subject_for(_disk(), None)
    entry = _logged(subject.disk, "hvc-022")
    record(entry)
    record(_logged("disk-ffffffffffffffff", "hvc-022"))

    # Act
    found = look_up(subject)

    # Assert
    assert found.entries == (entry,)


def test_a_drive_is_looked_up_in_the_logbook() -> None:
    # Arrange
    entry = _logged(None, "twin")
    record(entry)
    record(_logged(None, "hvc-022"))

    # Act
    found = look_up(subject_for(None, "twin"))

    # Assert
    assert found.entries == (entry,)


def test_the_payload_lists_entries_and_what_changed() -> None:
    # Arrange
    subject = subject_for(_disk(), None)
    first = _logged(subject.disk, "hvc-022")
    second = replace(first, run="later", recorded="2026-11-16T17:00:00Z", weak=((0, 3), (0, 7)))
    record(first)
    record(second)

    # Act
    payload = log_payload(subject, look_up(subject))

    # Assert
    assert payload == {
        "subject": subject.title,
        "entries": [
            {
                "recorded": "2026-11-01T10:00:00Z",
                "kind": "dump",
                "grade": "clean",
                "title": GAME,
                "drive": "hvc-022",
                "weak": [[0, 3]],
            },
            {
                "recorded": "2026-11-16T17:00:00Z",
                "kind": "dump",
                "grade": "clean",
                "title": GAME,
                "drive": "hvc-022",
                "weak": [[0, 3], [0, 7]],
            },
        ],
        "weakened": [[0, 7]],
        "settled": [],
        "since": "2026-11-01T10:00:00Z",
        "lines": [
            f"2026-11-01 10:00  dump         clean      {GAME}  1 weak: side 0 block 3",
            (
                f"2026-11-16 17:00  dump         clean      {GAME}  2 weak: side 0 block 3, "
                "side 0 block 7"
            ),
            "since the dump of 2026-11-01 10:00, 1 block(s) weakened: side 0 block 7",
        ],
    }


def test_an_empty_history_has_no_since() -> None:
    # Arrange
    subject = subject_for(None, "nobody")

    # Act
    payload = log_payload(subject, look_up(subject))

    # Assert
    assert payload["since"] is None
    assert payload["entries"] == []
