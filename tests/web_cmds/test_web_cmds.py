from __future__ import annotations

import logging
import sys
import webbrowser
from typing import TYPE_CHECKING

from fastapi import FastAPI
from hid_double import FakeHid
from main_kit import PUBLISHED_HOST, runner
from server_double import FakeUvicorn

from fdstoolkit.cli import web_cmds
from fdstoolkit.cli.main import app

if TYPE_CHECKING:
    import pytest


def test_web_starts_the_application(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    server = FakeUvicorn()
    monkeypatch.setitem(sys.modules, "uvicorn", server)

    # Act
    result = runner.invoke(app, ["web", "--port", "9123", "--no-open"])

    # Assert
    assert result.exit_code == 0
    assert server.started == [("127.0.0.1", 9123)]
    assert isinstance(server.apps[0], FastAPI)


def test_web_starts_hidapi_on_the_main_thread_before_it_serves(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    order: list[str] = []

    class PrimedHid(FakeHid):
        def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, object]]:
            order.append("prime")
            return super().enumerate(vendor_id, product_id)

    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn(order))
    monkeypatch.setitem(sys.modules, "hid", PrimedHid([]))

    # Act
    result = runner.invoke(app, ["web", "--no-open"])

    # Assert
    assert result.exit_code == 0
    assert order == ["prime", "run"]


def test_web_verbose_prints_every_job_step(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn())
    package = logging.getLogger("fdstoolkit")
    before = (package.level, list(package.handlers))

    # Act
    result = runner.invoke(app, ["web", "--verbose", "--no-open"])

    # Assert
    level, handlers = package.level, list(package.handlers)
    package.setLevel(before[0])
    package.handlers = before[1]
    assert result.exit_code == 0
    assert level == logging.DEBUG
    assert len(handlers) == len(before[1]) + 1


def test_web_says_which_extra_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "uvicorn", None)

    # Act
    result = runner.invoke(app, ["web"])

    # Assert
    assert result.exit_code == 1
    assert "brew install" in result.stdout


def test_the_web_server_loader_returns_a_runner_and_a_factory() -> None:
    # Arrange
    loader = web_cmds.web_server

    # Act
    run, build = loader()

    # Assert
    assert callable(run)
    assert callable(build)


def test_web_opens_a_browser_unless_told_not_to(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    opened: list[str] = []

    def remember(address: str) -> bool:
        opened.append(address)
        return True

    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn())
    monkeypatch.setattr(webbrowser, "open", remember)

    # Act
    result = runner.invoke(app, ["web", "--port", "9124"])

    # Assert
    assert result.exit_code == 0
    assert opened == ["http://127.0.0.1:9124"]


def test_a_loopback_bind_says_nothing_leaves_this_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn())

    # Act
    result = runner.invoke(app, ["web", "--host", "127.0.0.1", "--no-open"])

    # Assert
    assert "nothing leaves this machine" in result.stdout


def test_a_published_bind_warns_instead_of_claiming_privacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setitem(sys.modules, "uvicorn", FakeUvicorn())

    # Act
    result = runner.invoke(app, ["web", "--host", PUBLISHED_HOST, "--no-open"])

    # Assert
    assert "nothing leaves this machine" not in result.stdout
    assert "there is no password" in result.stdout
