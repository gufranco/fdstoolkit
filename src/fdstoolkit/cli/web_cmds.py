from __future__ import annotations

import logging
import webbrowser
from collections.abc import Callable
from typing import Annotated, Final

import typer

from fdstoolkit.cli.common import (
    fail,
)
from fdstoolkit.hardware.fdsstick import prime_hid


def web_server() -> tuple[Callable[..., None], Callable[..., object]]:
    import uvicorn  # noqa: PLC0415

    from fdstoolkit.ui.app import create_app  # noqa: PLC0415

    return uvicorn.run, create_app


def _require_web() -> tuple[Callable[..., None], Callable[..., object]]:
    try:
        return web_server()
    except ImportError as error:
        raise fail(UI_HINT) from error


UI_HINT: Final = (
    "this build carries no web interface, which a Homebrew install always does. "
    "Reinstall with: brew install gufranco/tap/fdstoolkit"
)

LOOPBACK: Final = frozenset({"127.0.0.1", "::1", "localhost"})


PACKAGE_LOGGER: Final = "fdstoolkit"


PUBLISHED_HINT: Final = (
    "anyone who can reach this machine on that port can drive it, and there is no password. "
    "Bind 127.0.0.1 unless you meant to publish it"
)


def _log_steps() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    package = logging.getLogger(PACKAGE_LOGGER)
    package.setLevel(logging.DEBUG)
    package.addHandler(handler)


def _start_web(*, host: str, port: int, open_browser: bool, verbose: bool = False) -> None:
    run, build = _require_web()
    prime_hid()
    if verbose:
        _log_steps()
    address = f"http://{host}:{port}"
    if host in LOOPBACK:
        typer.echo(f"serving on {address}, and nothing leaves this machine")
    else:
        typer.echo(f"serving on {address}")
        typer.echo(PUBLISHED_HINT)
    if open_browser:
        webbrowser.open(address)
    run(build(allowed_hosts=frozenset({host})), host=host, port=port)


def web(
    *,
    host: Annotated[str, typer.Option("--host", help="which interface to bind")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", min=1, max=65535)] = 8000,
    no_open: Annotated[
        bool,
        typer.Option("--no-open", help="start the server without opening a browser"),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", help="print every step of every disk job in this terminal"),
    ] = False,
) -> None:
    _start_web(host=host, port=port, open_browser=not no_open, verbose=verbose)


def register(app: typer.Typer) -> None:
    app.command(
        help="Open the local web interface, which reports exactly what these commands report."
    )(web)
