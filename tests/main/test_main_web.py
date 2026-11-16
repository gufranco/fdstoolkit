from __future__ import annotations

import json
import sys
from typing import TYPE_CHECKING

from hid_double import FakeHid, stick
from main_kit import runner

from fdstoolkit.cli.main import app

if TYPE_CHECKING:
    import pytest


def test_status_reports_a_ready_stick_and_what_it_cannot_say(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "hid", FakeHid([stick()]))

    # Act
    result = runner.invoke(app, ["status"])

    # Assert
    assert result.exit_code == 0
    assert "1 device(s) connected" in result.stdout
    assert "reports nothing about the disk itself" in result.stdout


def test_status_fails_and_marks_a_missing_stick(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "hid", FakeHid([]))

    # Act
    result = runner.invoke(app, ["status"])

    # Assert
    assert result.exit_code == 1
    assert "none connected at 16D0:0AAA" in result.stdout
    assert "[warning]" in result.stdout


def test_status_can_print_json(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "hid", FakeHid([]))

    # Act
    result = runner.invoke(app, ["status", "--json"])

    # Assert
    payload = json.loads(result.stdout)
    assert result.exit_code == 1
    assert payload["ready"] is False
    assert [check["name"] for check in payload["checks"]] == ["hardware support", "fdsstick"]
