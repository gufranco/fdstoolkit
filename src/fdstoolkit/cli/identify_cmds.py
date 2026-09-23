from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.build.targets import TARGETS, export_for, swap_warnings
from fdstoolkit.cli.common import (
    Container,
    TargetChoice,
    container_of,
    decode_image,
    fail,
    guard_output,
    read_image,
)
from fdstoolkit.codecs import fds, qd
from fdstoolkit.codecs.ares import decode_side
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.identify.cache import DatCache
from fdstoolkit.identify.dat import Catalogue, Identification, MatchKind, load_dat
from fdstoolkit.identify.dat import identify as identify_image
from fdstoolkit.identify.firmware import emulator_notes, extract_bios, identify_bios
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


def dat_cache(
    *,
    clear: Annotated[bool, typer.Option("--clear", help="remove every cached catalogue")] = False,
) -> None:
    """Show or clear the parsed DAT cache."""
    cache = DatCache()
    if clear:
        typer.echo(f"removed {cache.clear()} cached catalogue(s) from {cache.root}")
        return
    entries = list(cache.entries())
    typer.echo(f"{cache.root}: {len(entries)} cached catalogue(s)")


def bios(
    file: Annotated[Path, typer.Argument(help="a BIOS file, 8 KB or wrapped in a larger dump")],
    *,
    extract: Annotated[
        Path | None, typer.Option("--extract", help="write the 8 KB BIOS found inside")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Identify a Famicom Disk System BIOS, and say which emulators accept it."""
    if not file.is_file():
        message = f"file not found: {file}"
        raise fail(message)
    data = file.read_bytes()
    report = identify_bios(data)
    notes = emulator_notes(report.revision, exact_size=report.exact_size)

    if extract is not None:
        guard_output(extract, force=force)
        try:
            extract.write_bytes(extract_bios(data))
        except ValueError as error:
            raise fail(str(error)) from error

    revision = report.revision
    if json_output:
        typer.echo(
            as_json(
                {
                    "path": str(file),
                    "size": report.size,
                    "offset": report.offset,
                    "crc32": report.crc32,
                    "sha1": report.sha1,
                    "revision": revision.name if revision else None,
                    "mame_name": revision.mame_name if revision else None,
                    "source": revision.source if revision else None,
                    "emulators": notes,
                }
            )
        )
    else:
        name = revision.name if revision else "unknown"
        typer.echo(f"{file.name}: {name}, {report.size} bytes")
        if report.offset:
            typer.echo(f"  the BIOS sits at offset {report.offset:#x} inside a larger dump")
        if report.crc32:
            typer.echo(f"  crc32 {report.crc32}  sha1 {report.sha1}")
        for emulator, verdict in notes.items():
            typer.echo(f"  {emulator:<8} {verdict}")
        if extract is not None:
            typer.echo(f"wrote {extract}")

    raise typer.Exit(code=0 if revision is not None else 1)


def export(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    target: Annotated[TargetChoice, typer.Option("--target", help="the device or emulator")],
    directory: Annotated[Path, typer.Option("-d", "--directory", help="the card or folder root")],
    *,
    bios: Annotated[
        Path | None, typer.Option("--bios", help="a BIOS to place where the target looks")
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="overwrite existing files")] = False,
) -> None:
    """Write an image in the layout a device or emulator expects."""
    disk, _, _, _ = decode_image(image)
    bios_data = None
    if bios is not None:
        if not bios.is_file():
            message = f"file not found: {bios}"
            raise fail(message)
        bios_data = bios.read_bytes()

    try:
        written = export_for(
            disk,
            target=target.value,
            directory=directory,
            stem=image.stem,
            bios=bios_data,
            force=force,
        )
    except FileExistsError as error:
        message = f"{error}, pass --force to overwrite"
        raise fail(message) from error
    except ValueError as error:
        raise fail(str(error)) from error

    typer.echo(TARGETS[target.value].description)
    for path in written:
        typer.echo(f"wrote {path}")
    for warning in swap_warnings(image.stem, target=target.value):
        typer.echo(f"  {warning}")


def import_ares(
    files: Annotated[list[Path], typer.Argument(help="ares side files, in side order")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the image")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Rebuild an image from ares per-side files, including any save they carry."""
    guard_output(output, force=force)
    sides: list[Side] = []
    for path in files:
        if not path.is_file():
            message = f"file not found: {path}"
            raise fail(message)
        try:
            sides.append(decode_side(path.read_bytes()))
        except ValueError as error:
            raise fail(str(error)) from error

    disk = Disk(sides=tuple(sides))
    if container_of(output) is Container.FDS:
        data, _ = fds.encode(disk, headered=False)
    else:
        data, _ = qd.encode(disk)
    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(sides)} side(s), {len(data)} bytes)")


def register(app: typer.Typer) -> None:
    app.command()(identify)
    app.command(name="dat-cache")(dat_cache)
    app.command()(bios)
    app.command()(export)
    app.command(name="import-ares")(import_ares)
