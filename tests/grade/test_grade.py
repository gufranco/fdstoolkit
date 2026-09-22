from __future__ import annotations

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.diagnostics import CODES, Diagnostic, Severity
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.hardware.session import Grade
from fdstoolkit.quality.confidence import score_disk
from fdstoolkit.quality.grade import grade_disk
from fdstoolkit.quality.reads import compare_reads


def _disk(*, valid: bool = True, tail: bytes = bytes(41)) -> Disk:
    payload = bytes([BlockKind.DISK_INFO]) + b"*NINTENDO-HVC*" + tail
    block = Block(kind=BlockKind.DISK_INFO, payload=payload)
    block = (
        block.with_computed_crc()
        if valid
        else Block(kind=BlockKind.DISK_INFO, payload=payload, stored_crc=0x1234)
    )
    return Disk(sides=(Side(blocks=(block,), tail=b"", capacity=65500),))


def _finding(code: str, severity: Severity) -> Diagnostic:
    return Diagnostic(code=code, severity=severity, message=CODES[code])


def test_a_clean_image_grades_clean() -> None:
    report = grade_disk(confidence=score_disk(_disk()))

    assert report.grade is Grade.CLEAN
    assert not report.failures


def test_an_error_finding_fails_the_image() -> None:
    report = grade_disk(
        confidence=score_disk(_disk()),
        findings=(_finding("FDS002", Severity.ERROR),),
    )

    assert report.grade is Grade.FAILED


def test_a_warning_finding_makes_the_image_marginal() -> None:
    report = grade_disk(
        confidence=score_disk(_disk()),
        findings=(_finding("FDS003", Severity.WARNING),),
    )

    assert report.grade is Grade.MARGINAL


def test_a_low_confidence_block_makes_the_image_unstable() -> None:
    bad = _disk(valid=False)

    report = grade_disk(confidence=score_disk(bad))

    assert report.grade in {Grade.UNSTABLE, Grade.FAILED}


def test_unstable_reads_make_the_image_marginal() -> None:
    stats = compare_reads([_disk(), _disk(), _disk(tail=bytes([9]) + bytes(40))])

    report = grade_disk(confidence=score_disk(_disk()), reads=stats)

    assert report.grade is not Grade.CLEAN


def test_every_reason_names_its_metric_and_threshold() -> None:
    report = grade_disk(confidence=score_disk(_disk()))

    for reason in report.reasons:
        assert reason.metric
        assert reason.render()


def test_the_report_renders_a_line_naming_the_grade() -> None:
    report = grade_disk(confidence=score_disk(_disk()))

    assert "clean" in report.render()


def test_the_report_carries_the_worst_confidence() -> None:
    confidence = score_disk(_disk())

    report = grade_disk(confidence=confidence)

    assert report.confidence == confidence.worst


def test_a_failed_report_names_what_failed() -> None:
    report = grade_disk(
        confidence=score_disk(_disk()),
        findings=(_finding("FDS002", Severity.ERROR),),
    )

    assert any(reason.metric == "errors" for reason in report.failures)
    assert "errors" in report.render()
