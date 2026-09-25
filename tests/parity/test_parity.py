from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.cli.main import app as cli_app
from fdstoolkit.ui.app import ROUTE_FOR_COMMAND, create_app

CLI_ONLY = {"web", "doctor"}


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app())


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
    missing = cli_commands() - CLI_ONLY - set(ROUTE_FOR_COMMAND)

    assert missing == set()


def test_the_map_names_no_command_the_cli_does_not_have() -> None:
    invented = set(ROUTE_FOR_COMMAND) - cli_commands()

    assert invented == set()


def test_every_mapped_route_is_registered() -> None:
    registered = web_routes()
    absent = {
        command: path for command, path in ROUTE_FOR_COMMAND.items() if path not in registered
    }

    assert absent == {}


def test_the_catalogue_lists_every_command(client: TestClient) -> None:
    listed = set(client.get("/api/catalogue").json()["commands"])

    assert listed == cli_commands() - CLI_ONLY


def test_only_the_server_and_the_install_check_are_left_out() -> None:
    assert CLI_ONLY.isdisjoint(ROUTE_FOR_COMMAND)
