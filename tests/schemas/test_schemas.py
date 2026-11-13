from __future__ import annotations

from typing import TYPE_CHECKING, get_args

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.diagnostics import Diagnostic, Severity
from fdstoolkit.core.diskinfo import PROFILES
from fdstoolkit.identify.hashes import digests_of
from fdstoolkit.quality.confidence import score_disk
from fdstoolkit.quality.grade import grade_disk
from fdstoolkit.quality.reads import compare_reads
from fdstoolkit.ui.schemas import (
    CalibrationResult,
    CalibrationRow,
    DiagnosticView,
    DigestView,
    DiskView,
    DumpedResult,
    FileResult,
    GradeResult,
    JobResult,
    JobView,
    ProfileView,
    ReadsResult,
    ReportedFile,
)

if TYPE_CHECKING:
    from pydantic import BaseModel

IMAGE = blank_image(sides=2, headered=False, formatted=True, game_name="SMB")


def sample_disk():  # noqa: ANN201
    disk, _ = decode(IMAGE)
    return disk


@pytest.mark.parametrize("name", sorted(PROFILES))
def test_every_profile_has_a_view(name: str) -> None:
    # Arrange
    masked = PROFILES[name].masked

    # Act
    view = ProfileView.of(name)

    # Assert
    assert view.name == name
    assert view.masks == sorted(masked)


def test_a_diagnostic_view_carries_its_code_and_severity() -> None:
    # Arrange
    finding = Diagnostic(
        code="FDS001",
        severity=Severity.WARNING,
        message="something",
        side=1,
        offset=42,
    )

    # Act
    view = DiagnosticView.of(finding)

    # Assert
    assert view.code == "FDS001"
    assert view.severity == str(Severity.WARNING)
    assert view.side == 1
    assert view.offset == 42


def test_a_disk_view_describes_every_side() -> None:
    # Arrange
    disk = sample_disk()

    # Act
    view = DiskView.of(disk)

    # Assert
    assert len(view.sides) == 2
    assert view.sides[0].index == 0
    assert view.sides[0].blocks


def test_a_disk_view_marks_a_file_past_the_declared_count_as_hidden() -> None:
    # Arrange
    disk = sample_disk()

    # Act
    view = DiskView.of(disk)

    # Assert
    assert all(not entry.hidden for entry in view.files)


def test_a_digest_view_carries_every_hash() -> None:
    # Arrange
    digests = digests_of(IMAGE)

    # Act
    view = DigestView.of(digests)

    # Assert
    assert view.size == len(IMAGE)
    assert len(view.sha256) == 64


def test_a_grade_view_carries_its_reasons() -> None:
    # Arrange
    disk, findings = decode(IMAGE)

    # Act
    view = GradeResult.of(grade_disk(confidence=score_disk(disk), findings=findings))

    # Assert
    assert view.grade
    assert view.reasons
    assert all(reason.metric for reason in view.reasons)


def test_a_reads_view_carries_the_decay_direction() -> None:
    # Arrange
    disk, _ = decode(IMAGE)

    # Act
    view = ReadsResult.of(compare_reads([disk, disk]))

    # Assert
    assert view.passes == 2
    assert view.stability == pytest.approx(1.0)
    assert view.decay


def test_a_job_result_is_read_back_as_the_model_that_made_it() -> None:
    # Arrange
    dumped = DumpedResult(name="dump.fds", data="AA==", size=1, grade="clean")
    reported = ReportedFile(headline="written", file=FileResult(name="b.fds", data="AA==", size=1))

    # Act
    views = [
        JobView.model_validate(
            {
                "id": "j",
                "command": "c",
                "writes": False,
                "state": "done",
                "result": made.model_dump(),
            }
        )
        for made in (dumped, reported)
    ]

    # Assert
    assert [type(view.result) for view in views] == [DumpedResult, ReportedFile]


def test_a_kept_file_is_typed() -> None:
    # Arrange
    kept = FileResult(name="backup.fds", data="AA==", size=1)

    # Act
    view = JobView.model_validate(
        {
            "id": "j",
            "command": "write",
            "writes": True,
            "state": "running",
            "kept": kept.model_dump(),
        }
    )

    # Assert
    assert view.kept == kept


def test_calibration_rows_are_typed() -> None:
    # Arrange
    row = CalibrationRow(
        read=8,
        expected=8,
        missing=[],
        short=0,
        long=0,
        invalid=0,
        lead_in=28300,
        verdict="reads clean",
    )

    # Act
    result = CalibrationResult.model_validate(
        {
            "headline": "h",
            "mode": "speed",
            "rows": [row.model_dump()],
            "ok": True,
            "spread": {},
            "timing": [],
        }
    )

    # Assert
    assert result.rows == [row]


def job_result_samples() -> dict[type[BaseModel], BaseModel]:
    file = FileResult(name="b.fds", data="AA==", size=1)
    row = CalibrationRow(
        read=8, expected=8, missing=[], short=0, long=0, invalid=0, lead_in=None, verdict="clean"
    )
    return {
        DumpedResult: DumpedResult(name="dump.fds", data="AA==", size=1, grade="clean"),
        CalibrationResult: CalibrationResult(
            headline="h", mode="speed", rows=[row], ok=True, spread={}, timing=[]
        ),
        ReportedFile: ReportedFile(headline="written", file=file),
    }


def test_every_job_result_model_has_a_sample() -> None:
    # Arrange
    iterable = get_args(get_args(JobResult)[0])

    # Act
    members = set(iterable)

    # Assert
    assert members == set(job_result_samples())


def test_every_job_result_model_reads_back_as_itself() -> None:
    # Arrange
    samples = job_result_samples()

    # Act
    read_back = {
        model: type(
            JobView.model_validate(
                {
                    "id": "j",
                    "command": "c",
                    "writes": False,
                    "state": "done",
                    "result": sample.model_dump(),
                }
            ).result
        )
        for model, sample in samples.items()
    }

    # Assert
    assert read_back == {model: model for model in samples}
