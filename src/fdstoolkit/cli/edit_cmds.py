from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.build.manifest import build_from_manifest, load_manifest
from fdstoolkit.cli.common import (
    KIND_FOR_CHOICE,
    Container,
    Family,
    KindChoice,
    container_of,
    decode_image,
    fail,
    guard_output,
    read_image,
)
from fdstoolkit.codecs import fds, qd
from fdstoolkit.edit.diskinfo import apply_edits, parse_edit
from fdstoolkit.edit.files import FileSpec, extract_files, insert_file
from fdstoolkit.edit.rebuild import RebuildOptions, rebuild
from fdstoolkit.patch.apply import apply_patch
from fdstoolkit.patch.formats import PatchError


def extract(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    directory: Annotated[Path, typer.Option("-d", "--directory", help="where to write the files")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite existing files")] = False,
) -> None:
    """Write every file on the disk to a directory."""
    disk, _, _, _ = decode_image(image)
    directory.mkdir(parents=True, exist_ok=True)

    for entry in extract_files(disk):
        stem = entry.name.strip() or f"file{entry.position}"
        target = directory / f"side{entry.side}-{entry.position:02d}-{stem}.bin"
        if target.exists() and not force:
            message = f"{target} exists, pass --force to overwrite"
            raise fail(message)
        target.write_bytes(entry.data)
        marker = " (hidden)" if entry.hidden else ""
        typer.echo(f"{target.name}  {entry.size} bytes{marker}")


def insert_command(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the result")],
    *,
    file: Annotated[Path, typer.Option("--file", help="the file to add")],
    name: Annotated[str, typer.Option("--name", help="eight characters at most")],
    address: Annotated[str, typer.Option("--address", help="load address, hex")] = "6000",
    kind: Annotated[
        KindChoice, typer.Option("--kind", help="what the BIOS does with the file")
    ] = KindChoice.PROGRAM,
    side: Annotated[int, typer.Option("--side", min=0, help="which side")] = 0,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Add a file to a side and write the result."""
    disk, _, _, _ = decode_image(image)
    guard_output(output, force=force)
    if not file.is_file():
        message = f"file not found: {file}"
        raise fail(message)

    try:
        spec = FileSpec(
            name=name,
            address=int(address, 16),
            kind=KIND_FOR_CHOICE[kind],
            data=file.read_bytes(),
        )
        updated = insert_file(disk, side=side, spec=spec)
    except ValueError as error:
        raise fail(str(error)) from error

    target = container_of(output)
    if target is Container.FDS:
        data, findings = fds.encode(updated, headered=False)
    else:
        data, findings = qd.encode(updated)

    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    for finding in findings:
        typer.echo(f"  {finding.render()}")


def patch_command(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    patch_file: Annotated[Path, typer.Option("--patch", help="an IPS, UPS or BPS patch")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the result")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Apply a patch, whether it was made for the headered or headerless image."""
    data, _ = read_image(image)
    if not patch_file.is_file():
        message = f"file not found: {patch_file}"
        raise fail(message)
    guard_output(output, force=force)

    try:
        outcome = apply_patch(patch_file.read_bytes(), data)
    except PatchError as error:
        raise fail(str(error)) from error

    output.write_bytes(outcome.data)
    typer.echo(
        f"applied {outcome.format} patch to the {outcome.applied_to}, "
        f"wrote {output} ({len(outcome.data)} bytes)"
    )


def rebuild_command(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the result")],
    *,
    keep_tail: Annotated[
        bool, typer.Option("--keep-tail", help="keep data after the last block")
    ] = False,
    reveal_hidden: Annotated[
        bool, typer.Option("--reveal-hidden", help="raise the file count to what the side holds")
    ] = False,
    drop_hidden: Annotated[
        bool, typer.Option("--drop-hidden", help="remove files past the declared count")
    ] = False,
    renumber: Annotated[
        bool, typer.Option("--renumber", help="renumber the files in order")
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Re-emit an image from its parsed model, repairing what can be repaired."""
    guard_output(output, force=force)
    disk, _, _, _ = decode_image(image)

    try:
        result, report = rebuild(
            disk,
            options=RebuildOptions(
                keep_tail=keep_tail,
                reveal_hidden=reveal_hidden,
                drop_hidden=drop_hidden,
                renumber=renumber,
            ),
        )
    except ValueError as error:
        raise fail(str(error)) from error

    if container_of(output) is Container.FDS:
        data, _ = fds.encode(result, headered=False)
    else:
        data, _ = qd.encode(result)
    output.write_bytes(data)

    for action in report.actions:
        typer.echo(f"side {action.side}: {action.detail}")
    if not report.changed:
        typer.echo("nothing to repair")
    typer.echo(f"wrote {output} ({len(data)} bytes)")


def set_command(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the result")],
    *,
    edit: Annotated[list[str], typer.Option("--set", help="field=value, repeatable")],
    side: Annotated[int, typer.Option("--side", min=0, help="which side")] = 0,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Change fields of a disk information block."""
    disk, _, _, _ = decode_image(image)
    guard_output(output, force=force)

    try:
        edits = dict(parse_edit(item) for item in edit)
        updated, changes = apply_edits(disk, side=side, edits=edits)
    except ValueError as error:
        raise fail(str(error)) from error

    target = container_of(output)
    if target is Container.FDS:
        data, _ = fds.encode(updated, headered=False)
    else:
        data, _ = qd.encode(updated)
    output.write_bytes(data)

    for change in changes:
        typer.echo(f"{change.field}: {change.before} -> {change.after}")
    typer.echo(f"wrote {output} ({len(data)} bytes)")


def build(
    manifest: Annotated[Path, typer.Argument(help="a JSON manifest describing the disk")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the image")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Build a disk image from a manifest."""
    if not manifest.is_file():
        message = f"file not found: {manifest}"
        raise fail(message)
    guard_output(output, force=force)

    try:
        data = build_from_manifest(load_manifest(manifest))
    except ValueError as error:
        raise fail(str(error)) from error

    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes)")


def register(app: typer.Typer) -> None:
    app.command(rich_help_panel=Family.REPAIR)(extract)
    app.command(name="insert", rich_help_panel=Family.REPAIR)(insert_command)
    app.command(name="patch", rich_help_panel=Family.REPAIR)(patch_command)
    app.command(name="rebuild", rich_help_panel=Family.REPAIR)(rebuild_command)
    app.command(name="set", rich_help_panel=Family.REPAIR)(set_command)
    app.command(rich_help_panel=Family.CONTAINER)(build)
