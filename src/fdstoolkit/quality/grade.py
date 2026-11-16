from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fdstoolkit.core.diagnostics import Diagnostic, Severity
from fdstoolkit.hardware.session import Grade
from fdstoolkit.quality.confidence import LOW_CONFIDENCE, ConfidenceReport
from fdstoolkit.quality.reads import ReadStatistics

STABLE_READS: Final = 1.0
NO_FINDINGS: Final = 0.0


@dataclass(frozen=True, slots=True)
class Reason:
    metric: str
    value: float
    threshold: float
    passed: bool

    def render(self) -> str:
        verdict = "within" if self.passed else "past"
        return f"{self.metric} {self.value:g} {verdict} {self.threshold:g}"


@dataclass(frozen=True, slots=True)
class GradedReport:
    grade: Grade
    reasons: tuple[Reason, ...]
    confidence: float

    @property
    def failures(self) -> tuple[Reason, ...]:
        return tuple(reason for reason in self.reasons if not reason.passed)

    def render(self) -> str:
        if not self.failures:
            return f"{self.grade.value}, confidence {self.confidence:.2f}"
        why = "; ".join(reason.render() for reason in self.failures)
        return f"{self.grade.value}, confidence {self.confidence:.2f}: {why}"


def _reasons(
    findings: Sequence[Diagnostic],
    worst: float,
    reads: ReadStatistics | None,
    weak_blocks: int | None,
) -> tuple[Reason, ...]:
    errors = sum(1 for finding in findings if finding.severity is Severity.ERROR)
    warnings = sum(1 for finding in findings if finding.severity is Severity.WARNING)
    stable = () if reads is None else (_reason("read stability", reads.stability, STABLE_READS),)
    weak = () if weak_blocks is None else (_absent("weak blocks", weak_blocks),)
    return (
        _absent("errors", errors),
        _absent("warnings", warnings),
        _reason("confidence", worst, LOW_CONFIDENCE),
        *stable,
        *weak,
    )


def _reason(metric: str, value: float, threshold: float) -> Reason:
    return Reason(metric=metric, value=value, threshold=threshold, passed=value >= threshold)


def _absent(metric: str, count: int) -> Reason:
    return Reason(metric=metric, value=count, threshold=NO_FINDINGS, passed=not count)


def _grade(reasons: tuple[Reason, ...], worst: float) -> Grade:
    if not reasons[0].passed:
        return Grade.FAILED
    if worst < LOW_CONFIDENCE:
        return Grade.UNSTABLE
    if any(not reason.passed for reason in reasons):
        return Grade.MARGINAL
    return Grade.CLEAN


def grade_disk(
    *,
    confidence: ConfidenceReport,
    findings: Sequence[Diagnostic] = (),
    reads: ReadStatistics | None = None,
    weak_blocks: int | None = None,
) -> GradedReport:
    worst = confidence.worst if confidence.blocks else 1.0
    reasons = _reasons(findings, worst, reads, weak_blocks)
    return GradedReport(grade=_grade(reasons, worst), reasons=reasons, confidence=worst)
