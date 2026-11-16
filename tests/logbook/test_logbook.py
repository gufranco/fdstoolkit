from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Final

import pytest

from fdstoolkit.history.logbook import (
    LOGBOOK_ENV,
    Entry,
    EntryKind,
    LogbookError,
    append,
    history,
    logbook_path,
    record,
)

if TYPE_CHECKING:
    from faker import Faker

PARALLEL: Final = 12
FIRST: Final = "2026-11-01T10:00:00Z"
SECOND: Final = "2026-11-16T17:00:00Z"


def _entry(fake: Faker) -> Entry:
    return Entry(
        run=fake.uuid4(),
        recorded=FIRST,
        kind=EntryKind.DUMP,
        disk=f"disk-{fake.hexify('^^^^^^^^^^^^^^^^')}",
        title=fake.lexify("????").upper(),
        stick=fake.bothify("FDS#####"),
        drive=fake.word(),
        grade="clean",
        weak=(),
    )


def test_an_appended_entry_reads_back_whole(tmp_path: Path, fake: Faker) -> None:
    # Arrange
    store = tmp_path / "log" / "logbook.sqlite3"
    entry = replace(_entry(fake), weak=((0, 3), (1, 7)))

    # Act
    append(store, entry)

    # Assert
    assert history(store, disk=entry.disk) == (entry,)


def test_a_disk_history_is_in_time_order_and_leaves_other_disks_out(
    tmp_path: Path, fake: Faker
) -> None:
    # Arrange
    store = tmp_path / "logbook.sqlite3"
    later = replace(_entry(fake), recorded=SECOND)
    earlier = replace(_entry(fake), disk=later.disk, recorded=FIRST)
    append(store, later)
    append(store, earlier)
    append(store, _entry(fake))

    # Act
    found = history(store, disk=later.disk)

    # Assert
    assert found == (earlier, later)


def test_a_drive_history_matches_the_label_on_any_stick(tmp_path: Path, fake: Faker) -> None:
    # Arrange
    store = tmp_path / "logbook.sqlite3"
    checked = replace(_entry(fake), kind=EntryKind.CALIBRATION, drive="hvc-022")
    other_stick = replace(
        _entry(fake), kind=EntryKind.CALIBRATION, drive="hvc-022", recorded=SECOND
    )
    append(store, checked)
    append(store, other_stick)
    append(store, replace(_entry(fake), drive="twin"))

    # Act
    found = history(store, drive="hvc-022")

    # Assert
    assert found == (checked, other_stick)


def test_a_missing_logbook_has_no_history(tmp_path: Path) -> None:
    # Arrange
    store = tmp_path / "never" / "logbook.sqlite3"

    # Act
    found = history(store, disk="disk-0000000000000000")

    # Assert
    assert found == ()
    assert not store.exists()


def test_parallel_appends_keep_every_entry(tmp_path: Path, fake: Faker) -> None:
    # Arrange
    store = tmp_path / "logbook.sqlite3"
    disk = "disk-1111111111111111"
    entries = [
        replace(_entry(fake), disk=disk, run=f"run-{index:02d}") for index in range(PARALLEL)
    ]

    # Act
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        list(pool.map(partial(append, store), entries))

    # Assert
    assert sorted(entry.run for entry in history(store, disk=disk)) == [
        f"run-{index:02d}" for index in range(PARALLEL)
    ]


def test_the_same_run_appended_in_parallel_is_kept_once(tmp_path: Path, fake: Faker) -> None:
    # Arrange
    store = tmp_path / "logbook.sqlite3"
    entry = _entry(fake)

    # Act
    with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
        list(pool.map(partial(append, store), [entry] * PARALLEL))

    # Assert
    assert history(store, disk=entry.disk) == (entry,)


def test_the_same_run_appended_twice_keeps_the_first(tmp_path: Path, fake: Faker) -> None:
    # Arrange
    store = tmp_path / "logbook.sqlite3"
    entry = _entry(fake)
    append(store, entry)

    # Act
    append(store, replace(_entry(fake), run=entry.run, disk=entry.disk, grade="failed"))

    # Assert
    assert history(store, disk=entry.disk) == (entry,)


def test_an_unwritable_logbook_names_its_path(tmp_path: Path, fake: Faker) -> None:
    # Arrange
    blocker = tmp_path / "file"
    blocker.write_bytes(b"")
    store = blocker / "logbook.sqlite3"

    # Act
    with pytest.raises(LogbookError) as raised:
        append(store, _entry(fake))

    # Assert
    assert str(raised.value).startswith(f"could not write the logbook at {store}: ")


def test_a_file_that_is_not_a_logbook_cannot_be_read(tmp_path: Path) -> None:
    # Arrange
    store = tmp_path / "logbook.sqlite3"
    store.write_bytes(b"not a database, only text that sqlite refuses to open " * 64)

    # Act
    with pytest.raises(LogbookError) as raised:
        history(store, disk="disk-0000000000000000")

    # Assert
    assert str(raised.value).startswith(f"could not read the logbook at {store}: ")


def test_the_setting_names_where_the_logbook_lives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    chosen = tmp_path / "chosen.sqlite3"
    monkeypatch.setenv(LOGBOOK_ENV, str(chosen))

    # Act
    found = logbook_path()

    # Assert
    assert found == chosen


def test_without_the_setting_the_logbook_lives_in_the_data_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.delenv(LOGBOOK_ENV, raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    # Act
    found = logbook_path()

    # Assert
    assert found == tmp_path / "data" / "fdstoolkit" / "logbook.sqlite3"


def test_without_a_data_folder_the_logbook_lives_under_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.delenv(LOGBOOK_ENV, raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    # Act
    found = logbook_path()

    # Assert
    assert found == tmp_path / ".local" / "share" / "fdstoolkit" / "logbook.sqlite3"


def test_a_recorded_entry_lands_in_the_configured_logbook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake: Faker
) -> None:
    # Arrange
    chosen = tmp_path / "chosen.sqlite3"
    monkeypatch.setenv(LOGBOOK_ENV, str(chosen))
    entry = _entry(fake)

    # Act
    record(entry)

    # Assert
    assert history(chosen, disk=entry.disk) == (entry,)
