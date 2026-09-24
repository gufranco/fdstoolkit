from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.build.manifest import build_from_manifest, load_manifest
from fdstoolkit.cli.common import (
    KIND_FOR_CHOICE,
    Container,
    KindChoice,
    container_of,
    decode_image,
    fail,
    guard_output,
    read_image,
)
from fdstoolkit.codecs import fds, qd
from fdstoolkit.codecs.mgd1 import SideFile, join_side_files, split_into_side_files
from fdstoolkit.core.disk import SIDES_PER_DISK
from fdstoolkit.edit.clean import clean_trailing_data
from fdstoolkit.edit.diskinfo import apply_edits, parse_edit
from fdstoolkit.edit.emulator import SaveFormat, extract_save, merge_save
from fdstoolkit.edit.files import FileSpec, extract_files, insert_file
from fdstoolkit.edit.rebuild import RebuildOptions, rebuild
from fdstoolkit.edit.recipes import load_recipes
from fdstoolkit.edit.saves import normalise_saves
from fdstoolkit.fdskey.card import FirmwareVariant, card_blank
from fdstoolkit.patch.apply import apply_patch
from fdstoolkit.patch.formats import PatchError
from fdstoolkit.quality.consensus import build_consensus


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


def clean(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the result")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Remove leftover bytes after the last block of every side."""
    disk, _, _, _ = decode_image(image)
    guard_output(output, force=force)

    cleaned, removed = clean_trailing_data(disk)
    target = container_of(output)
    if target is Container.FDS:
        data, _ = fds.encode(cleaned, headered=False)
    else:
        data, _ = qd.encode(cleaned)
    output.write_bytes(data)

    for entry in removed:
        typer.echo(f"side {entry.side}: removed {entry.bytes_removed} trailing byte(s)")
    typer.echo(f"wrote {output} ({len(data)} bytes)")


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


def save_apply(
    image: Annotated[Path, typer.Argument(help="the original image")],
    save: Annotated[Path, typer.Option("--save", help="an emulator save, IPS or whole image")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the result")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Merge an emulator save back into a disk image."""
    data, _ = read_image(image)
    if not save.is_file():
        message = f"file not found: {save}"
        raise fail(message)
    guard_output(output, force=force)

    try:
        merged = merge_save(data, save.read_bytes())
    except PatchError as error:
        raise fail(str(error)) from error

    output.write_bytes(merged)
    typer.echo(f"wrote {output} ({len(merged)} bytes)")


def save_extract(
    original_image: Annotated[Path, typer.Argument(help="the pristine image")],
    played: Annotated[Path, typer.Option("--played", help="the image a game wrote to")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the save")],
    *,
    fmt: Annotated[SaveFormat, typer.Option("--format", help="ips, ups or image")] = SaveFormat.IPS,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Write the difference between a pristine disk and a played one as a save."""
    pristine, _ = read_image(original_image)
    if not played.is_file():
        message = f"file not found: {played}"
        raise fail(message)
    guard_output(output, force=force)

    try:
        save = extract_save(pristine, played.read_bytes(), fmt=fmt)
    except PatchError as error:
        raise fail(str(error)) from error

    output.write_bytes(save)
    typer.echo(f"wrote {output} ({len(save)} bytes, {fmt})")


def normalise_saves_command(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the result")],
    *,
    recipes: Annotated[Path, typer.Option("--recipes", help="a recipe file")],
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Fill a declared save region so two played copies compare equal."""
    disk, _, _, _ = decode_image(image)
    if not recipes.is_file():
        message = f"file not found: {recipes}"
        raise fail(message)
    guard_output(output, force=force)

    try:
        updated, applied = normalise_saves(disk, load_recipes(recipes))
    except ValueError as error:
        raise fail(str(error)) from error

    target = container_of(output)
    if target is Container.FDS:
        data, _ = fds.encode(updated, headered=False)
    else:
        data, _ = qd.encode(updated)
    output.write_bytes(data)

    for entry in applied:
        typer.echo(
            f"side {entry.side} file {entry.position} {entry.name}: "
            f"{entry.size} bytes filled with {entry.fill:#04x}"
        )
    if not applied:
        typer.echo("no recipe matched this disk, so nothing changed")
    typer.echo(f"wrote {output} ({len(data)} bytes)")


def split(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    directory: Annotated[Path, typer.Option("-d", "--directory", help="where to write the sides")],
    *,
    stem: Annotated[str, typer.Option("--stem", help="base name for the side files")] = "fc1234",
    force: Annotated[bool, typer.Option("--force", help="overwrite existing files")] = False,
) -> None:
    """Split an image into one file per side, the way a Game Doctor stores it."""
    data, _ = read_image(image)
    directory.mkdir(parents=True, exist_ok=True)

    for entry in split_into_side_files(data, stem=stem):
        target = directory / entry.name
        if target.exists() and not force:
            message = f"{target} exists, pass --force to overwrite"
            raise fail(message)
        target.write_bytes(entry.data)
        typer.echo(f"{entry.name}  {len(entry.data)} bytes")


def join(
    files: Annotated[list[Path], typer.Argument(help="the side files, in any order")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the image")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Join per-side files back into one image."""
    guard_output(output, force=force)
    sides: list[SideFile] = []
    for path in files:
        if not path.is_file():
            message = f"file not found: {path}"
            raise fail(message)
        sides.append(SideFile(name=path.name, data=path.read_bytes()))

    try:
        data = join_side_files(sides)
    except ValueError as error:
        raise fail(str(error)) from error

    output.write_bytes(data)
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


def card(
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the blank")],
    *,
    sides: Annotated[
        int, typer.Option("--sides", min=1, max=SIDES_PER_DISK, help="1 or 2 sides")
    ] = 1,
    variant: Annotated[
        FirmwareVariant,
        typer.Option("--firmware", help="released accepts an all-zero blank, master does not"),
    ] = FirmwareVariant.MASTER,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Write a blank image an FDSKey card will accept."""
    guard_output(output, force=force)
    data = card_blank(sides=sides, variant=variant)
    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes, for {variant} firmware)")


def consensus(
    images: Annotated[list[Path], typer.Argument(help="two or more dumps of one disk")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the merge")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
    stability_map: Annotated[
        bool, typer.Option("--map", help="print the per-block stability map")
    ] = False,
) -> None:
    """Merge several dumps of one disk, block by block, and report every disagreement."""
    guard_output(output, force=force)
    disks = [decode_image(path)[0] for path in images]

    try:
        result = build_consensus(disks)
    except ValueError as error:
        raise fail(str(error)) from error

    data, _ = fds.encode(result.disk, headered=False)
    output.write_bytes(data)

    if stability_map:
        for entry in result.stability:
            typer.echo(
                f"side {entry.side} block {entry.block:3d}  {entry.kind:<11} "
                f"{entry.agreement:6.1%}  {entry.variants} variant(s)  {entry.verdict}"
            )
    for side_index, block_index in result.disagreements:
        typer.echo(f"side {side_index} block {block_index}: the dumps disagree")
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    raise typer.Exit(code=0 if not result.disagreements else 1)


def register(app: typer.Typer) -> None:
    app.command()(extract)
    app.command(name="insert")(insert_command)
    app.command(name="patch")(patch_command)
    app.command()(clean)
    app.command(name="rebuild")(rebuild_command)
    app.command(name="set")(set_command)
    app.command(name="save-apply")(save_apply)
    app.command(name="save-extract")(save_extract)
    app.command(name="normalise-saves")(normalise_saves_command)
    app.command()(split)
    app.command()(join)
    app.command()(build)
    app.command()(card)
    app.command()(consensus)
