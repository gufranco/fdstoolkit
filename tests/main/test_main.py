from __future__ import annotations

from main_kit import runner

from fdstoolkit.cli.main import app


def test_the_version_flag_prints_the_version() -> None:
    # Arrange
    arguments = ["--version"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert result.stdout.startswith("fdstoolkit ")


def test_the_help_lists_the_commands() -> None:
    # Arrange
    arguments = ["--help"]

    # Act
    result = runner.invoke(app, arguments)

    # Assert
    assert result.exit_code == 0
    assert "verify" in result.stdout
