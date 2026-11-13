from __future__ import annotations

import json

from fdstoolkit.core.diagnostics import Diagnostic, Severity
from fdstoolkit.report import as_json, diagnostics_as_data


def test_a_diagnostic_becomes_a_flat_record() -> None:
    # Arrange
    finding = Diagnostic(
        code="FDS002",
        severity=Severity.ERROR,
        message="block CRC does not match the data",
        side=1,
        offset=0x3A,
        detail={"stored": 1, "computed": 2},
    )

    # Act
    record = diagnostics_as_data([finding])[0]

    # Assert
    assert record["code"] == "FDS002"
    assert record["severity"] == "error"
    assert record["side"] == 1
    assert record["detail"] == {"computed": 2, "stored": 1}


def test_detail_keys_are_sorted_so_output_is_stable() -> None:
    # Arrange
    finding = Diagnostic(
        code="FDS006",
        severity=Severity.INFO,
        message="files present beyond the declared file count",
        detail={"zulu": 1, "alpha": 2},
    )

    # Act
    record = diagnostics_as_data([finding])[0]

    # Assert
    assert list(record["detail"]) == ["alpha", "zulu"]  # type: ignore[arg-type]


def test_json_output_sorts_its_keys() -> None:
    # Arrange
    payload = {"zulu": 1, "alpha": 2}

    # Act
    text = as_json(payload)

    # Assert
    assert text.index("alpha") < text.index("zulu")
    assert json.loads(text) == {"zulu": 1, "alpha": 2}


def test_json_output_is_identical_across_calls() -> None:
    # Arrange
    payload: dict[str, object] = {"b": [1, 2], "a": {"y": 1, "x": 2}}

    # Act
    rendered = as_json(payload)

    # Assert
    assert rendered == as_json(payload)


def test_json_output_keeps_non_ascii_readable() -> None:
    # Arrange
    payload = {"name": "ação"}

    # Act
    rendered = as_json(payload)

    # Assert
    assert "ção" in rendered
