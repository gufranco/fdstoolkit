from __future__ import annotations

import json

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.session import dump
from fdstoolkit.hardware.simulation import FaultPlan, SimulatedDrive
from fdstoolkit.submit.log import DumpLog, load_log, log_of


def sample_disk(sides: int = 1) -> Disk:
    disk, _ = decode(blank_image(sides=sides, headered=False, formatted=True, game_name="SMB"))
    return disk


def clean_log() -> DumpLog:
    result = dump(SimulatedDrive(sample_disk()), sides=1)
    return log_of(result, backend="fdsstick", device="loopy FDSStick, firmware 1.04")


def test_a_log_names_the_tool_and_the_device() -> None:
    log = clean_log()

    assert log.tool.startswith("fdstoolkit ")
    assert log.backend == "fdsstick"
    assert log.device is not None
    assert "firmware 1.04" in log.device


def test_a_log_dates_itself() -> None:
    log = clean_log()

    assert len(log.taken) == len("2026-09-22")
    assert log.taken.count("-") == 2


def test_a_clean_dump_reports_no_retries_and_no_failures() -> None:
    log = clean_log()

    assert log.retried_blocks == ()
    assert log.failed_blocks == ()
    assert log.clean


def test_a_retried_block_is_named_with_its_attempt_count() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(flaky_blocks={1: 3}))

    log = log_of(dump(drive, sides=1, retries=4), backend="fdsstick")

    assert len(log.retried_blocks) == 1
    assert log.retried_blocks[0].block == 1
    assert log.retried_blocks[0].attempts == 3
    assert log.retried_blocks[0].recovered


def test_the_settings_a_dump_ran_with_are_recorded() -> None:
    result = dump(SimulatedDrive(sample_disk()), sides=1)

    log = log_of(result, backend="fdsstick", settings={"retries": 5, "passes": 2})

    assert log.settings["retries"] == 5


def test_a_simulated_dump_says_so_rather_than_passing_as_hardware() -> None:
    result = dump(SimulatedDrive(sample_disk()), sides=1)

    log = log_of(result, backend="simulation", simulated=True)

    assert log.simulated
    assert "simulated drive" in log.render()


def test_the_rendered_log_names_every_retry() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(flaky_blocks={1: 3}))

    text = log_of(dump(drive, sides=1, retries=4), backend="fdsstick").render()

    assert "block 1 needed 3 attempts" in text
    assert "recovered" in text


def test_a_log_round_trips_through_json() -> None:
    original = clean_log()

    restored = load_log(original.as_json())

    assert restored.tool == original.tool
    assert restored.taken == original.taken
    assert restored.grade == original.grade
    assert len(restored.sides) == len(original.sides)


def test_the_json_carries_a_version_so_a_reader_can_refuse_it() -> None:
    data = json.loads(clean_log().as_json())

    assert data["log_version"] == 1


def test_a_log_from_a_future_version_is_refused() -> None:
    data = json.loads(clean_log().as_json())
    data["log_version"] = 99

    with pytest.raises(ValueError, match="version 99"):
        load_log(json.dumps(data))


def test_a_two_side_dump_records_both_sides() -> None:
    result = dump(SimulatedDrive(sample_disk(sides=2)), sides=2)

    log = log_of(result, backend="simulation", simulated=True)

    assert [side.index for side in log.sides] == [0, 1]
    assert all(side.blocks for side in log.sides)


def test_a_given_date_is_used_rather_than_today() -> None:
    result = dump(SimulatedDrive(sample_disk()), sides=1)

    log = log_of(result, backend="fdsstick", taken="2026-01-31")

    assert log.taken == "2026-01-31"


def test_a_log_built_with_no_settings_carries_an_empty_table() -> None:
    log = DumpLog(
        tool="fdstoolkit test",
        backend="fdsstick",
        taken="2026-09-23",
        sides=(),
        grade="clean",
    )

    assert log.settings == {}
    assert "setting" not in log.render()


def test_a_block_that_never_read_cleanly_is_named_in_the_log() -> None:
    drive = SimulatedDrive(sample_disk(), plan=FaultPlan(bad_crc_blocks=frozenset({1})))

    text = log_of(dump(drive, sides=1, retries=2), backend="fdsstick").render()

    assert "never read cleanly" in text
