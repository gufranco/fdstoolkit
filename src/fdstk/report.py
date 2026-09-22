from __future__ import annotations

import json
from collections.abc import Sequence

from fdstk.core.diagnostics import Diagnostic


def diagnostics_as_data(findings: Sequence[Diagnostic]) -> list[dict[str, object]]:
    return [
        {
            "code": finding.code,
            "severity": str(finding.severity),
            "message": finding.message,
            "side": finding.side,
            "offset": finding.offset,
            "detail": dict(sorted(finding.detail.items())),
        }
        for finding in findings
    ]


def as_json(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=False)
