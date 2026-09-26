from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

CODES: Final[Mapping[str, str]] = {
    "FDS001": "side carries no disk information block",
    "FDS002": "block CRC does not match the data",
    "FDS003": "block CRC is null rather than computed",
    "FDS004": "block is truncated before its declared length",
    "FDS005": "unexpected block code where another kind was expected",
    "FDS006": "files present beyond the declared file count",
    "FDS007": "non-zero bytes after the last block",
    "FDS008": "disk verification string is missing or altered",
    "FDS009": "declared file count does not match the files found",
    "FDS010": "image size is not a whole number of sides",
    "FDS011": "side content exceeds the capacity of the target format",
    "FDS012": "file data block is shorter than its header declares",
    "FDS013": "header side count disagrees with the data present",
    "FDS014": "no block was recovered from the pulse stream",
    "FDS015": "a decoded region does not start with the sync mark",
    "FDS016": "file data block runs past the size its header declares",
}


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


ORDER: Final[Mapping[Severity, int]] = {
    Severity.INFO: 0,
    Severity.WARNING: 1,
    Severity.ERROR: 2,
}


@dataclass(frozen=True, slots=True)
class Diagnostic:
    code: str
    severity: Severity
    message: str
    side: int | None = None
    offset: int | None = None
    detail: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def render(self) -> str:
        body = f"[{self.code}] {self.message}"
        if self.side is None:
            return body
        return f"side {self.side}: {body}"


def worst_severity(findings: Sequence[Diagnostic]) -> Severity:
    worst = Severity.INFO
    for finding in findings:
        if ORDER[finding.severity] > ORDER[worst]:
            worst = finding.severity
    return worst
