from __future__ import annotations

from typing import Annotated

import typer

from fdstoolkit import __version__
from fdstoolkit.cli import (
    compare_cmds,
    convert_cmds,
    drive_cli,
    edit_cmds,
    hardware_cmds,
    inspect_cmds,
    master_cli,
    quality_cli,
    save_cmds,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Famicom Disk System preservation toolkit.",
)

compare_cmds.register(app)
convert_cmds.register(app)
edit_cmds.register(app)
inspect_cmds.register(app)
hardware_cmds.register(app)
quality_cli.register(app)
master_cli.register(app)
drive_cli.register(app)
save_cmds.register(app)


def _version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(f"fdstoolkit {__version__}")
    raise typer.Exit(code=0)


@app.callback()
def main(
    *,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, help="print the version and exit"),
    ] = False,
) -> None:
    """Famicom Disk System preservation toolkit."""
    del version
