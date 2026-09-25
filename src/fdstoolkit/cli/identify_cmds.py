from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.build.targets import TARGETS, export_for, swap_warnings
from fdstoolkit.cli.common import (
    Family,
    TargetChoice,
    decode_image,
    fail,
    read_image,
)
from fdstoolkit.identify.cache import DatCache
from fdstoolkit.identify.dat import Catalogue, Identification, MatchKind, load_dat
from fdstoolkit.identify.dat import identify as identify_image
from fdstoolkit.identify.near import NearMatch, nearest_match, reference_images
from fdstoolkit.report import as_json


def identify(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    dat: Annotated[Path, typer.Option("--dat", help="a No-Intro style DAT file")],
    *,
    reference: Annotated[
        Path | None,
        typer.Option("--reference", help="a directory of known images, for a near match"),
    ] = None,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="parse the DAT instead of reading the cache")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Match an image against a DAT, and say what it matched on."""
    data, _ = read_image(image)
    try:
        catalogue, cached = _catalogue(dat, no_cache=no_cache)
    except ValueError as error:
        raise fail(str(error)) from error

    result = identify_image(data, catalogue)
    payload: dict[str, object] = {
        "path": str(image),
        "dat": catalogue.name,
        "dat_version": catalogue.version,
        "cached": cached,
        "kind": str(result.kind),
        "name": result.entry.name if result.entry else None,
        "matched_on": result.matched_on,
        "same_size": [entry.name for entry in result.same_size],
    }

    near = (
        nearest_match(data, reference_images(reference, skip=image))
        if reference is not None and result.kind is not MatchKind.EXACT
        else None
    )
    if near is not None:
        payload["nearest"] = {
            "path": str(near.path),
            "near": near.near,
            "differing_bytes": near.diff.differing_bytes,
            "ratio": round(near.diff.ratio, 6),
            "first_offset": near.diff.first_offset,
            "last_offset": near.diff.last_offset,
            "runs": [list(run) for run in near.diff.runs],
            "truncated_runs": near.diff.truncated_runs,
        }

    if json_output:
        typer.echo(as_json(payload))
    else:
        _print_identification(result, near)

    raise typer.Exit(code=0 if result.kind is MatchKind.EXACT else 1)


def _catalogue(dat: Path, *, no_cache: bool) -> tuple[Catalogue, bool]:
    if no_cache:
        if not dat.is_file():
            message = f"file not found: {dat}"
            raise ValueError(message)
        return load_dat(dat), False
    return DatCache().load(dat)


def _print_identification(result: Identification, near: NearMatch | None) -> None:
    if result.entry is not None:
        typer.echo(f"{result.entry.name}  (matched on {result.matched_on})")
        return

    typer.echo("no match")
    for entry in result.same_size:
        typer.echo(f"  same size: {entry.name}")
    if near is None:
        return

    label = "near match" if near.near else "nearest candidate"
    typer.echo(
        f"  {label}: {near.path.name}, {near.diff.differing_bytes} byte(s) differ "
        f"({near.diff.ratio:.4%})"
    )
    for offset, length in near.diff.runs:
        typer.echo(f"    0x{offset:06x}  {length} byte(s)")
    if near.diff.truncated_runs:
        typer.echo("    more runs not shown")


def export(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    target: Annotated[TargetChoice, typer.Option("--target", help="the device or emulator")],
    directory: Annotated[Path, typer.Option("-d", "--directory", help="the card or folder root")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite existing files")] = False,
) -> None:
    """Write an image in the layout a device or emulator expects."""
    disk, _, _, _ = decode_image(image)

    try:
        written = export_for(
            disk,
            target=target.value,
            directory=directory,
            stem=image.stem,
            force=force,
        )
    except FileExistsError as error:
        message = f"{error}, pass --force to overwrite"
        raise fail(message) from error

    typer.echo(TARGETS[target.value].description)
    for path in written:
        typer.echo(f"wrote {path}")
    for warning in swap_warnings(image.stem, target=target.value):
        typer.echo(f"  {warning}")


def register(app: typer.Typer) -> None:
    app.command(rich_help_panel=Family.IDENTIFY)(identify)
    app.command(rich_help_panel=Family.CONTAINER)(export)
