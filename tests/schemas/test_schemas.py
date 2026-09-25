from __future__ import annotations

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
    DiagnosticView,
    DigestView,
    DiskView,
    GradeResult,
    ProfileView,
    ReadsResult,
)

IMAGE = blank_image(sides=2, headered=False, formatted=True, game_name="SMB")


def sample_disk():  # noqa: ANN201
    disk, _ = decode(IMAGE)
    return disk


@pytest.mark.parametrize("name", sorted(PROFILES))
def test_every_profile_has_a_view(name: str) -> None:
    view = ProfileView.of(name)

    assert view.name == name
    assert view.masks == sorted(PROFILES[name].masked)


def test_a_diagnostic_view_carries_its_code_and_severity() -> None:
    finding = Diagnostic(
        code="FDS001",
        severity=Severity.WARNING,
        message="something",
        side=1,
        offset=42,
    )

    view = DiagnosticView.of(finding)

    assert view.code == "FDS001"
    assert view.severity == str(Severity.WARNING)
    assert view.side == 1
    assert view.offset == 42


def test_a_disk_view_describes_every_side() -> None:
    view = DiskView.of(sample_disk())

    assert len(view.sides) == 2
    assert view.sides[0].index == 0
    assert view.sides[0].blocks


def test_a_disk_view_marks_a_file_past_the_declared_count_as_hidden() -> None:
    view = DiskView.of(sample_disk())

    assert all(not entry.hidden for entry in view.files)


def test_a_digest_view_carries_every_hash() -> None:
    view = DigestView.of(digests_of(IMAGE))

    assert view.size == len(IMAGE)
    assert len(view.sha256) == 64


def test_a_grade_view_carries_its_reasons() -> None:
    disk, findings = decode(IMAGE)

    view = GradeResult.of(grade_disk(confidence=score_disk(disk), findings=findings))

    assert view.grade
    assert view.reasons
    assert all(reason.metric for reason in view.reasons)


def test_a_reads_view_carries_the_decay_direction() -> None:
    disk, _ = decode(IMAGE)

    view = ReadsResult.of(compare_reads([disk, disk]))

    assert view.passes == 2
    assert view.stability == pytest.approx(1.0)
    assert view.decay
