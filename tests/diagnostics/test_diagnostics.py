from __future__ import annotations

from fdstoolkit.core.diagnostics import CODES, Diagnostic, Severity, worst_severity


def test_a_diagnostic_carries_its_code_and_location() -> None:
    # Arrange
    code = "FDS002"
    message = "block CRC does not match"
    side = 1
    offset = 0x3A
    detail = {"stored": 0x1234, "computed": 0x5678}

    # Act
    finding = Diagnostic(
        code=code,
        severity=Severity.ERROR,
        message=message,
        side=side,
        offset=offset,
        detail=detail,
    )

    # Assert
    assert finding.code == "FDS002"
    assert finding.side == 1
    assert finding.offset == 0x3A
    assert finding.detail["stored"] == 0x1234


def test_a_diagnostic_renders_a_single_line() -> None:
    # Arrange
    code = "FDS001"
    message = "side is unformatted"
    side = 0

    # Act
    finding = Diagnostic(
        code=code,
        severity=Severity.WARNING,
        message=message,
        side=side,
    )

    # Assert
    assert finding.render() == "side 0: [FDS001] side is unformatted"


def test_a_diagnostic_without_a_side_renders_without_the_prefix() -> None:
    # Arrange
    code = "FDS010"
    message = "size is not a multiple"

    # Act
    finding = Diagnostic(code=code, severity=Severity.ERROR, message=message)

    # Assert
    assert finding.render() == "[FDS010] size is not a multiple"


def test_worst_severity_of_nothing_is_info() -> None:
    # Arrange
    findings = ()

    # Act
    result = worst_severity(findings)

    # Assert
    assert result is Severity.INFO


def test_worst_severity_picks_the_highest() -> None:
    # Arrange
    expected = Severity.ERROR

    # Act
    findings = (
        Diagnostic(code="FDS001", severity=Severity.WARNING, message="one"),
        Diagnostic(code="FDS002", severity=Severity.ERROR, message="two"),
        Diagnostic(code="FDS006", severity=Severity.INFO, message="three"),
    )

    # Assert
    assert worst_severity(findings) is expected


def test_every_code_has_a_description() -> None:
    # Arrange
    codes = CODES

    # Act
    undescribed = [code for code, description in codes.items() if not description]

    # Assert
    assert undescribed == []
    assert all(code.startswith("FDS") for code in codes)
