from __future__ import annotations

from fdstk.core.diagnostics import CODES, Diagnostic, Severity, worst_severity


def test_a_diagnostic_carries_its_code_and_location() -> None:
    finding = Diagnostic(
        code="FDS002",
        severity=Severity.ERROR,
        message="block CRC does not match",
        side=1,
        offset=0x3A,
        detail={"stored": 0x1234, "computed": 0x5678},
    )

    assert finding.code == "FDS002"
    assert finding.side == 1
    assert finding.offset == 0x3A
    assert finding.detail["stored"] == 0x1234


def test_a_diagnostic_renders_a_single_line() -> None:
    finding = Diagnostic(
        code="FDS001",
        severity=Severity.WARNING,
        message="side is unformatted",
        side=0,
    )

    assert finding.render() == "side 0: [FDS001] side is unformatted"


def test_a_diagnostic_without_a_side_renders_without_the_prefix() -> None:
    finding = Diagnostic(code="FDS010", severity=Severity.ERROR, message="size is not a multiple")

    assert finding.render() == "[FDS010] size is not a multiple"


def test_worst_severity_of_nothing_is_info() -> None:
    assert worst_severity(()) is Severity.INFO


def test_worst_severity_picks_the_highest() -> None:
    findings = (
        Diagnostic(code="FDS001", severity=Severity.WARNING, message="one"),
        Diagnostic(code="FDS002", severity=Severity.ERROR, message="two"),
        Diagnostic(code="FDS006", severity=Severity.INFO, message="three"),
    )

    assert worst_severity(findings) is Severity.ERROR


def test_every_code_has_a_description() -> None:
    for code, description in CODES.items():
        assert code.startswith("FDS")
        assert description
