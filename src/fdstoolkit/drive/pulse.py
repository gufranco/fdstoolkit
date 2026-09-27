from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Final

from fdstoolkit.codecs.raw import decode_packed
from fdstoolkit.core.diagnostics import Diagnostic
from fdstoolkit.drive.captures import Capture

PULSE_CODES: Final = frozenset({"FDS004", "FDS015", "FDS016", "FDS017", "FDS019"})

Key = tuple[int, str, object]


@dataclass(frozen=True, slots=True)
class PulseFinding:
    side: int
    read: int
    finding: Diagnostic

    @property
    def key(self) -> Key:
        return (self.side, self.finding.code, self.finding.detail.get("block"))


def findings_of(side: int, read: int, found: Sequence[Diagnostic]) -> tuple[PulseFinding, ...]:
    return tuple(
        PulseFinding(side=side, read=read, finding=finding)
        for finding in found
        if finding.code in PULSE_CODES
    )


def captured_findings(captures: Sequence[Capture]) -> tuple[PulseFinding, ...]:
    return tuple(
        item
        for capture in captures
        for item in findings_of(capture.side, capture.read, decode_packed(capture.data)[1])
    )


def settled(
    findings: Sequence[PulseFinding], captures: Sequence[Capture]
) -> tuple[Diagnostic, ...]:
    reads = Counter(capture.side for capture in captures)
    first = {item.key: item for item in reversed(findings)}
    seen_in = Counter(key for key, _ in {(item.key, item.read) for item in findings})
    return tuple(
        replace(first[key].finding, side=first[key].side)
        for key in dict.fromkeys(item.key for item in findings)
        if seen_in[key] >= reads[first[key].side]
    )


def _where(finding: Diagnostic) -> str:
    block = finding.detail.get("block")
    bits = finding.detail.get("bits")
    parts = [
        *([] if block is None else [f"block {block}"]),
        *([] if bits is None else [f"{bits} bits"]),
    ]
    return f" ({', '.join(parts)})" if parts else ""


def pulse_lines(findings: Sequence[PulseFinding], captures: Sequence[Capture]) -> tuple[str, ...]:
    kept = settled(findings, captures)
    passing = len({item.key for item in findings}) - len(kept)
    note = (
        f"{passing} pulse finding(s) appeared in only some reads of a side, so they "
        "belong to those reads rather than to the disk"
    )
    return (
        *(f"{finding.render()}{_where(finding)}" for finding in kept),
        *((note,) if passing else ()),
    )


def bundle_findings(captures: Sequence[Capture]) -> tuple[Diagnostic, ...]:
    return settled(captured_findings(captures), captures)
