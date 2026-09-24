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


def grade_disk(
    *,
    confidence: ConfidenceReport,
    findings: Sequence[Diagnostic] = (),
    reads: ReadStatistics | None = None,
) -> GradedReport:
    errors = sum(1 for finding in findings if finding.severity is Severity.ERROR)
    warnings = sum(1 for finding in findings if finding.severity is Severity.WARNING)
    worst = confidence.worst if confidence.blocks else 1.0

    reasons = [
        Reason(metric="errors", value=errors, threshold=NO_FINDINGS, passed=not errors),
        Reason(metric="warnings", value=warnings, threshold=NO_FINDINGS, passed=not warnings),
        Reason(
            metric="confidence",
            value=worst,
            threshold=LOW_CONFIDENCE,
            passed=worst >= LOW_CONFIDENCE,
        ),
    ]

    if reads is not None:
        reasons.append(
            Reason(
                metric="read stability",
                value=reads.stability,
                threshold=STABLE_READS,
                passed=reads.stability >= STABLE_READS,
            )
        )

    if errors:
        grade = Grade.FAILED
    elif worst < LOW_CONFIDENCE:
        grade = Grade.UNSTABLE
    elif any(not reason.passed for reason in reasons):
        grade = Grade.MARGINAL
    else:
        grade = Grade.CLEAN

    return GradedReport(grade=grade, reasons=tuple(reasons), confidence=worst)
