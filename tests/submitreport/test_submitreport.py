from __future__ import annotations

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.disk import Disk
from fdstoolkit.hardware.session import dump
from fdstoolkit.hardware.simulation import SimulatedDrive
from fdstoolkit.submit.log import log_of
from fdstoolkit.submit.report import EVIDENCE, Submission, submission_for


def sample_disk(sides: int = 1) -> Disk:
    disk, _ = decode(blank_image(sides=sides, headered=False, formatted=True, game_name="SMB"))
    return disk


def sample_image() -> bytes:
    return blank_image(sides=1, headered=False, formatted=True, game_name="SMB")


def sample_log():  # noqa: ANN201
    return log_of(
        dump(SimulatedDrive(sample_disk()), sides=1),
        backend="fdsstick",
        device="loopy FDSStick, firmware 1.04",
        taken="2026-09-22",
    )


def built() -> Submission:
    return submission_for(sample_image(), name="disk.fds", log=sample_log(), dumper="someone")


def test_a_submission_carries_every_hash_the_guide_requires() -> None:
    entry = built().files[0]

    assert entry.size == len(sample_image())
    assert len(entry.crc32) == 8
    assert len(entry.md5) == 32
    assert len(entry.sha1) == 40
    assert len(entry.sha256) == 64


def test_a_submission_names_the_tool_and_the_device() -> None:
    text = built().render()

    assert "fdstoolkit" in text
    assert "loopy FDSStick, firmware 1.04" in text


def test_a_submission_carries_the_date_the_dump_was_taken() -> None:
    assert "2026-09-22" in built().render()


def test_a_submission_names_the_dumper() -> None:
    assert "someone" in built().render()


def test_a_submission_carries_the_dump_log() -> None:
    text = built().render()

    assert "blocks read" in text
    assert "grade" in text


def test_a_submission_lists_the_evidence_the_toolkit_cannot_supply() -> None:
    missing = built().missing_evidence

    assert missing == EVIDENCE
    assert any("PCB" in item for item in missing)


def test_supplying_a_photograph_removes_it_from_the_missing_list() -> None:
    report = submission_for(
        sample_image(),
        name="disk.fds",
        log=sample_log(),
        dumper="someone",
        evidence=("media.jpg", "pcb.jpg", "packaging.jpg"),
    )

    assert report.missing_evidence == ()
    assert "media.jpg" in report.render()


def test_the_metadata_the_image_declares_is_carried() -> None:
    text = built().render()

    assert "SMB" in text


def test_a_simulated_dump_is_refused_as_a_submission() -> None:
    simulated = log_of(
        dump(SimulatedDrive(sample_disk()), sides=1),
        backend="simulation",
        simulated=True,
    )

    with pytest.raises(ValueError, match="simulated"):
        submission_for(sample_image(), name="disk.fds", log=simulated, dumper="someone")


def test_the_identity_digest_answers_the_rewrite_date_problem() -> None:
    text = built().render()

    assert "fdstoolkit:v1:release" in text


def test_a_submission_with_several_files_carries_each_one() -> None:
    report = submission_for(
        sample_image(),
        name="disk.fds",
        log=sample_log(),
        dumper="someone",
        extra={"disk.raw03": b"\x55" * 64},
    )

    assert [entry.name for entry in report.files] == ["disk.fds", "disk.raw03"]
    assert "disk.raw03" in report.render()


def test_an_unnamed_dumper_is_refused() -> None:
    with pytest.raises(ValueError, match="dumper"):
        submission_for(sample_image(), name="disk.fds", log=sample_log(), dumper="")


def test_an_affiliation_is_credited_when_given() -> None:
    report = submission_for(
        sample_image(),
        name="disk.fds",
        log=sample_log(),
        dumper="someone",
        affiliation="a preservation group",
    )

    assert "Affiliation (if applicable): a preservation group" in report.render()


def test_a_dump_with_no_device_still_renders() -> None:
    log = log_of(dump(SimulatedDrive(sample_disk()), sides=1), backend="dumper")

    report = submission_for(sample_image(), name="disk.fds", log=log, dumper="someone")

    assert "Dump tool: fdstoolkit" in report.render()
    assert "dumper" in report.render()


def test_the_settings_the_dump_used_are_quoted() -> None:
    log = log_of(
        dump(SimulatedDrive(sample_disk()), sides=1),
        backend="fdsstick",
        settings={"retries": 5},
    )

    report = submission_for(sample_image(), name="disk.fds", log=log, dumper="someone")

    assert "non-default settings: retries=5" in report.render()


def test_an_image_with_no_game_name_reports_it_as_unknown() -> None:
    plain = blank_image(sides=1, headered=False, formatted=True)

    report = submission_for(plain, name="disk.fds", log=sample_log(), dumper="someone")

    assert report.game == "unknown"


def test_an_unformatted_image_reports_no_game_name() -> None:
    empty = blank_image(sides=1, headered=False, formatted=False)

    report = submission_for(empty, name="disk.fds", log=sample_log(), dumper="someone")

    assert report.game == "unknown"


TEMPLATE_LABELS = (
    "Game name:",
    "Dumper (person who dumped the ROM):",
    "Affiliation (if applicable):",
    "Dump tool:",
    "Date dump was created on (YYYY-MM-DD):",
    "Dump logs:",
    "--ROM(s)/file(s)--",
    "Size (bytes):",
    "CRC32:",
    "MD5 hash:",
    "SHA-1 hash:",
    "SHA-256 hash:",
    "Links/attachments to Cart/PCB/box photos/scans:",
)


@pytest.mark.parametrize("label", TEMPLATE_LABELS)
def test_every_published_label_appears_verbatim(label: str) -> None:
    assert label in built().render()


def test_the_labels_appear_in_the_published_order() -> None:
    text = built().render()
    positions = [text.index(label) for label in TEMPLATE_LABELS]

    assert positions == sorted(positions)


def test_an_affiliation_nobody_gave_is_left_blank_rather_than_dropped() -> None:
    assert "Affiliation (if applicable): \n" in built().render()


def test_the_tool_line_names_the_hardware_and_the_settings() -> None:
    line = built().tool_line

    assert "fdstoolkit" in line
    assert "loopy FDSStick" in line
    assert "default settings" in line


def test_the_region_and_revision_come_from_the_disk() -> None:
    metadata = built().metadata

    assert metadata["ROM Region"] == "Japan"
    assert metadata["Languages"] == "Japanese"
    assert metadata["ROM Revision"] == "0"


def test_the_media_serial_comes_from_the_writer_stamp() -> None:
    assert built().metadata["Physical Media Serial 2"] == "ffff"


def test_a_field_the_disk_cannot_answer_is_present_and_empty() -> None:
    metadata = built().metadata

    assert metadata["Box Barcode"] == ""
    assert "Box Barcode:" in built().render()


def test_the_photograph_requirement_names_the_chip_serials() -> None:
    assert any("serials on the chips" in item for item in EVIDENCE)
