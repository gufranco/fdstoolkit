from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final

import typer

from fdstoolkit.cli.common import (
    Family,
    ForceOption,
    decode_image,
    encoded_for,
    fail,
    guard_output,
    read_image,
)
from fdstoolkit.core.disk import Disk
from fdstoolkit.edit.emulator import SaveFormat, extract_save, merge_save
from fdstoolkit.edit.recipes import load_recipes
from fdstoolkit.edit.saves import find_save_candidates, normalise_saves
from fdstoolkit.patch.formats import PatchError
from fdstoolkit.report import as_json

MIN_DUMPS: Final = 2


class SaveAction(StrEnum):
    FIND = "find"
    APPLY = "apply"
    EXTRACT = "extract"
    BLANK = "blank"


@dataclass(frozen=True, slots=True)
class SaveRequest:
    images: list[Path]
    save: Path | None
    played: Path | None
    recipes: Path | None
    output: Path | None
    fmt: SaveFormat
    force: bool
    json_output: bool


def _existing(path: Path | None, flag: str, action: SaveAction) -> Path:
    if path is None:
        message = f"save {action} needs {flag}"
        raise fail(message)
    if not path.is_file():
        message = f"file not found: {path}"
        raise fail(message)
    return path


def _output(request: SaveRequest, action: SaveAction) -> Path:
    if request.output is None:
        message = f"save {action} writes a file, so pass -o"
        raise fail(message)
    guard_output(request.output, force=request.force)
    return request.output


def _one_image(request: SaveRequest, action: SaveAction) -> Path:
    if len(request.images) != 1:
        message = f"save {action} works on one image"
        raise fail(message)
    return request.images[0]


def _encoded(disk: Disk, output: Path) -> bytes:
    data, _ = encoded_for(disk, output)
    return data


def _find(request: SaveRequest) -> None:
    if len(request.images) < MIN_DUMPS:
        message = "save find compares two or more dumps of one release"
        raise fail(message)
    try:
        candidates = find_save_candidates([decode_image(path)[0] for path in request.images])
    except ValueError as error:
        raise fail(str(error)) from error
    rows = [
        {
            "side": candidate.side,
            "position": candidate.position,
            "name": candidate.name,
            "size": candidate.size,
            "differing_bytes": candidate.differing_bytes,
            "name_matches_pattern": candidate.name_matches_pattern,
        }
        for candidate in candidates
    ]
    if request.json_output:
        typer.echo(as_json({"images": [str(path) for path in request.images], "candidates": rows}))
        return
    if not rows:
        typer.echo("no save candidate: every file agrees across the dumps")
    for row in rows:
        marker = ", name reads like a save" if row["name_matches_pattern"] else ""
        typer.echo(
            f"side {row['side']} file {row['position']} {row['name']}: "
            f"{row['differing_bytes']} of {row['size']} bytes differ{marker}"
        )


def _apply(request: SaveRequest) -> None:
    data, _ = read_image(_one_image(request, SaveAction.APPLY))
    save = _existing(request.save, "--save", SaveAction.APPLY)
    output = _output(request, SaveAction.APPLY)
    try:
        merged = merge_save(data, save.read_bytes())
    except PatchError as error:
        raise fail(str(error)) from error
    output.write_bytes(merged)
    typer.echo(f"wrote {output} ({len(merged)} bytes)")


def _extract(request: SaveRequest) -> None:
    pristine, _ = read_image(_one_image(request, SaveAction.EXTRACT))
    played = _existing(request.played, "--played", SaveAction.EXTRACT)
    output = _output(request, SaveAction.EXTRACT)
    try:
        save = extract_save(pristine, played.read_bytes(), fmt=request.fmt)
    except PatchError as error:
        raise fail(str(error)) from error
    output.write_bytes(save)
    typer.echo(f"wrote {output} ({len(save)} bytes, {request.fmt})")


def _blank(request: SaveRequest) -> None:
    disk, _, _, _ = decode_image(_one_image(request, SaveAction.BLANK))
    recipes = _existing(request.recipes, "--recipes", SaveAction.BLANK)
    output = _output(request, SaveAction.BLANK)
    try:
        updated, applied = normalise_saves(disk, load_recipes(recipes))
    except ValueError as error:
        raise fail(str(error)) from error
    data = _encoded(updated, output)
    output.write_bytes(data)
    for entry in applied:
        typer.echo(
            f"side {entry.side} file {entry.position} {entry.name}: "
            f"{entry.size} bytes filled with {entry.fill:#04x}"
        )
    if not applied:
        typer.echo("no recipe matched this disk, so nothing changed")
    typer.echo(f"wrote {output} ({len(data)} bytes)")


ACTIONS: Final[dict[SaveAction, Callable[[SaveRequest], None]]] = {
    SaveAction.FIND: _find,
    SaveAction.APPLY: _apply,
    SaveAction.EXTRACT: _extract,
    SaveAction.BLANK: _blank,
}


ActionArgument = Annotated[
    SaveAction, typer.Argument(help="find the save, apply one, extract one, or blank it out")
]
ImagesArgument = Annotated[
    list[Path], typer.Argument(help="the image, or for find two or more dumps of one release")
]
SaveOption = Annotated[
    Path | None, typer.Option("--save", help="apply: an emulator save, a patch or an image")
]
PlayedOption = Annotated[
    Path | None, typer.Option("--played", help="extract: the image a game wrote to")
]
RecipesOption = Annotated[
    Path | None, typer.Option("--recipes", help="blank: the file naming each save region")
]
MaybeOutputOption = Annotated[
    Path | None, typer.Option("-o", "--output", help="where to write the result")
]
FormatOption = Annotated[SaveFormat, typer.Option("--format", help="extract: ips, ups or image")]
FindJsonOption = Annotated[bool, typer.Option("--json", help="find: emit JSON")]


def save(
    action: ActionArgument,
    images: ImagesArgument,
    *,
    save_file: SaveOption = None,
    played: PlayedOption = None,
    recipes: RecipesOption = None,
    output: MaybeOutputOption = None,
    fmt: FormatOption = SaveFormat.IPS,
    force: ForceOption = False,
    json_output: FindJsonOption = False,
) -> None:
    request = SaveRequest(
        images=images,
        save=save_file,
        played=played,
        recipes=recipes,
        output=output,
        fmt=fmt,
        force=force,
        json_output=json_output,
    )
    ACTIONS[action](request)


def register(app: typer.Typer) -> None:
    app.command(
        rich_help_panel=Family.REPAIR,
        help="Find the file that holds a game's save, and apply, extract or blank that save.",
    )(save)
