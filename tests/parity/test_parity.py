from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.cli.main import app as cli_app
from fdstoolkit.ui.app import ROUTE_FOR_COMMAND, create_app

CLI_ONLY = {"web", "doctor"}


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app(), base_url="http://127.0.0.1")


def cli_commands() -> set[str]:
    return {
        command.name or command.callback.__name__.replace("_", "-")
        for command in cli_app.registered_commands
        if command.callback is not None
    }


def web_routes() -> set[str]:
    found: set[str] = set()
    for route in create_app().routes:
        path = getattr(route, "path", "")
        if isinstance(path, str) and path.startswith("/api/"):
            found.add(path)
    return found


def test_every_command_has_a_route() -> None:
    # Arrange
    expected: set[str] = set()

    # Act
    missing = cli_commands() - CLI_ONLY - set(ROUTE_FOR_COMMAND)

    # Assert
    assert missing == expected


def test_the_map_names_no_command_the_cli_does_not_have() -> None:
    # Arrange
    expected: set[str] = set()

    # Act
    invented = set(ROUTE_FOR_COMMAND) - cli_commands()

    # Assert
    assert invented == expected


def test_every_mapped_route_is_registered() -> None:
    # Arrange
    registered = web_routes()

    # Act
    absent = {
        command: path for command, path in ROUTE_FOR_COMMAND.items() if path not in registered
    }

    # Assert
    assert absent == {}


def test_the_catalogue_lists_every_command(client: TestClient) -> None:
    # Arrange
    iterable = client.get("/api/catalogue").json()["commands"]

    # Act
    listed = set(iterable)

    # Assert
    assert listed == cli_commands() - CLI_ONLY


def test_only_the_server_and_the_install_check_are_left_out() -> None:
    # Arrange
    left_out = CLI_ONLY

    # Act
    routed = left_out & set(ROUTE_FOR_COMMAND)

    # Assert
    assert routed == set()
