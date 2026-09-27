from __future__ import annotations

from fdstoolkit.codecs.raw import (
    GAP_VALUE,
    block_regions,
    encode_block_stream,
    pack_raw03,
    unpack_raw03,
)
from fdstoolkit.core.diagnostics import CODES, Diagnostic, Severity
from fdstoolkit.drive.captures import Capture
from fdstoolkit.drive.pulse import captured_findings, findings_of, pulse_lines, settled

SHORT_GAP = 482
PAYLOADS = (bytes([0x01]) + bytes(55), bytes([0x02, 0x00]))


def side_values() -> bytes:
    return unpack_raw03(encode_block_stream(list(PAYLOADS)))


def shortened(values: bytes) -> bytes:
    regions = block_regions(values)
    return values[: regions[0][1]] + bytes([GAP_VALUE]) * SHORT_GAP + values[regions[1][0] :]


def capture(read: int, values: bytes) -> Capture:
    return Capture(side=0, read=read, data=pack_raw03(values))


def test_a_finding_every_read_of_a_side_reports_is_kept_with_its_side() -> None:
    captures = [capture(1, shortened(side_values())), capture(2, shortened(side_values()))]

    kept = settled(captured_findings(captures), captures)

    assert [(finding.code, finding.side, finding.detail["block"]) for finding in kept] == [
        ("FDS017", 0, 1)
    ]


def test_a_finding_only_one_read_reports_is_put_down_to_that_read() -> None:
    captures = [capture(1, shortened(side_values())), capture(2, side_values())]

    lines = pulse_lines(captured_findings(captures), captures)

    assert lines == (
        (
            "1 pulse finding(s) appeared in only some reads of a side, so they belong to "
            "those reads rather than to the disk"
        ),
    )


def test_a_kept_finding_names_its_block_and_gap_length() -> None:
    captures = [capture(1, shortened(side_values()))]

    lines = pulse_lines(captured_findings(captures), captures)

    assert len(lines) == 1
    assert lines[0].startswith("side 0: [FDS017] ")
    assert "(block 1, " in lines[0]
    assert lines[0].endswith(" bits)")


def test_a_clean_side_has_nothing_to_report() -> None:
    captures = [capture(1, side_values()), capture(2, side_values())]

    lines = pulse_lines(captured_findings(captures), captures)

    assert lines == ()


def test_a_checksum_failure_is_left_to_the_block_report() -> None:
    failed = Diagnostic(code="FDS002", severity=Severity.ERROR, message=CODES["FDS002"])

    kept = findings_of(0, 1, [failed])

    assert kept == ()


def test_a_finding_without_a_block_names_nothing_after_it() -> None:
    lost = Diagnostic(code="FDS015", severity=Severity.WARNING, message=CODES["FDS015"])
    captures = [capture(1, side_values())]

    lines = pulse_lines(findings_of(0, 1, [lost]), captures)

    assert lines == (f"side 0: [FDS015] {CODES['FDS015']}",)
