from __future__ import annotations

import pytest

from fdstoolkit.drive.fault import Fault, Observation, Risk, classify

FULL = 100


def _seen(name: str, bad: tuple[int, ...] = (), *, answered: bool = True) -> Observation:
    return Observation(name=name, blocks=FULL, failed=bad, answered=answered)


def test_a_clean_run_across_disks_reports_no_fault() -> None:
    report = classify([_seen("a"), _seen("b")])

    assert report.fault is Fault.NONE
    assert report.risk is Risk.SAFE


def test_a_drive_that_stopped_answering_is_a_bus_fault() -> None:
    report = classify([_seen("a", (5,)), _seen("b", answered=False)])

    assert report.fault is Fault.BUS
    assert report.risk is Risk.STOP


def test_a_bus_fault_forbids_trying_another_disk() -> None:
    report = classify([_seen("a", answered=False)])

    assert report.retries == 0
    assert "another disk" in report.render()


def test_errors_at_the_same_place_on_every_disk_are_the_drive() -> None:
    report = classify([_seen("a", (10, 40)), _seen("b", (10, 41)), _seen("c", (11, 40))])

    assert report.fault is Fault.DRIVE
    assert report.shared


def test_errors_on_one_disk_only_are_the_media() -> None:
    report = classify([_seen("a", (10, 40)), _seen("b"), _seen("c")])

    assert report.fault is Fault.MEDIA
    assert report.unique["a"] == (10, 40)


def test_a_drive_fault_leaves_the_media_unblamed() -> None:
    report = classify([_seen("a", (10,)), _seen("b", (10,))])

    assert not report.unique


def test_shared_and_private_errors_together_read_as_mixed() -> None:
    report = classify([_seen("a", (10, 70)), _seen("b", (10,)), _seen("c", (11,))])

    assert report.fault is Fault.MIXED


def test_one_disk_alone_cannot_separate_drive_from_media() -> None:
    report = classify([_seen("a", (10,))])

    assert report.fault is Fault.UNKNOWN
    assert "one disk" in report.render()


def test_a_single_clean_disk_still_reports_no_fault() -> None:
    assert classify([_seen("a")]).fault is Fault.NONE


def test_classifying_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one"):
        classify([])


def test_a_media_fault_allows_careful_retries() -> None:
    report = classify([_seen("a", (10,)), _seen("b"), _seen("c")])

    assert report.risk is Risk.FRAGILE
    assert 0 < report.retries <= 3


def test_a_clean_run_allows_the_usual_retries() -> None:
    assert classify([_seen("a"), _seen("b")]).retries == 3


def test_a_drive_fault_warns_before_the_next_disk() -> None:
    text = classify([_seen("a", (10,)), _seen("b", (10,))]).render()

    assert "drive" in text
    assert "align" in text


def test_positions_close_together_count_as_the_same_place() -> None:
    report = classify([_seen("a", (50,)), _seen("b", (52,))])

    assert report.fault is Fault.DRIVE


def test_positions_far_apart_do_not_count_as_the_same_place() -> None:
    report = classify([_seen("a", (10,)), _seen("b", (80,))])

    assert report.fault is Fault.MEDIA


def test_a_media_fault_names_the_disk_it_sits_on() -> None:
    text = classify([_seen("falsion", (10,)), _seen("b"), _seen("c")]).render()

    assert "falsion" in text
    assert "media" in text
