from __future__ import annotations

from pathlib import Path
from typing import Annotated, Final

import typer

from fdstoolkit.build.fdspacker_export import MANIFEST_NAME, FdsPackerExport
from fdstoolkit.build.manifest import build_manifest_file
from fdstoolkit.build.packaged import build_packaged
from fdstoolkit.cli.common import (
    KIND_FOR_CHOICE,
    Family,
    ForceOption,
    ImageArgument,
    KindChoice,
    ManifestChoice,
    OutputOption,
    decode_image,
    encoded_for,
    fail,
    guard_output,
    read_image,
)
from fdstoolkit.core.disk import Disk
from fdstoolkit.core.files import extract_files, extracted_name
from fdstoolkit.edit.diskinfo import apply_edits, parse_edit
from fdstoolkit.edit.files import DEFAULT_LOAD_ADDRESS, FileSpec, insert_file
from fdstoolkit.edit.rebuild import RebuildOptions, RebuildReport, rebuild
from fdstoolkit.patch.apply import apply_patch
from fdstoolkit.patch.formats import PatchError

ZIP_SUFFIX: Final = ".zip"


def extract(
    image: ImageArgument,
    directory: Annotated[Path, typer.Option("-d", "--directory", help="where to write the files")],
    *,
    manifest: Annotated[
        ManifestChoice | None,
        typer.Option("--manifest", help="also write a manifest that rebuilds the disk"),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="overwrite existing files")] = False,
) -> None:
    disk, _, _, _ = decode_image(image)
    if manifest is ManifestChoice.FDSPACKER:
        _extract_fdspacker(disk, directory, force=force)
        return
    directory.mkdir(parents=True, exist_ok=True)

    for entry in extract_files(disk):
        target = directory / extracted_name(entry)
        _refuse_overwrite(target, force=force)
        target.write_bytes(entry.data)
        marker = " (hidden)" if entry.hidden else ""
        typer.echo(f"{target.name}  {entry.size} bytes{marker}")


def _refuse_overwrite(target: Path, *, force: bool) -> None:
    if target.exists() and not force:
        message = f"{target} exists, pass --force to overwrite"
        raise fail(message)


def _extract_fdspacker(disk: Disk, directory: Path, *, force: bool) -> None:
    try:
        export = FdsPackerExport.of(disk)
    except ValueError as error:
        raise fail(str(error)) from error
    written = [*export.files, (MANIFEST_NAME, export.text().encode("utf-8"))]
    for relative, _ in written:
        _refuse_overwrite(directory / relative, force=force)
    for relative, data in written:
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        typer.echo(f"{relative}  {len(data)} bytes")


FileOption = Annotated[Path, typer.Option("--file", help="the file to add")]
NameOption = Annotated[str, typer.Option("--name", help="eight characters at most")]
AddressOption = Annotated[str, typer.Option("--address", help="load address, hex")]
KindOption = Annotated[KindChoice, typer.Option("--kind", help="what the BIOS does with the file")]
SideOption = Annotated[int, typer.Option("--side", min=0, help="which side")]


def _inserted(disk: Disk, side: int, spec: FileSpec) -> Disk:
    try:
        return insert_file(disk, side=side, spec=spec)
    except ValueError as error:
        raise fail(str(error)) from error


def _spec(file: Path, name: str, address: str, kind: KindChoice) -> FileSpec:
    if not file.is_file():
        message = f"file not found: {file}"
        raise fail(message)
    try:
        return FileSpec(
            name=name, address=int(address, 16), kind=KIND_FOR_CHOICE[kind], data=file.read_bytes()
        )
    except ValueError as error:
        raise fail(str(error)) from error


def insert_command(
    image: ImageArgument,
    output: OutputOption,
    *,
    file: FileOption,
    name: NameOption,
    address: AddressOption = f"{DEFAULT_LOAD_ADDRESS:X}",
    kind: KindOption = KindChoice.PROGRAM,
    side: SideOption = 0,
    force: ForceOption = False,
) -> None:
    disk, _, _, _ = decode_image(image)
    guard_output(output, force=force)
    updated = _inserted(disk, side, _spec(file, name, address, kind))
    data, findings = encoded_for(updated, output)
    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    for finding in findings:
        typer.echo(f"  {finding.render()}")


def patch_command(
    image: ImageArgument,
    patch_file: Annotated[Path, typer.Option("--patch", help="an IPS, UPS or BPS patch")],
    output: OutputOption,
    *,
    force: ForceOption = False,
) -> None:
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


KeepTailOption = Annotated[bool, typer.Option("--keep-tail", help="keep data after the last block")]
RevealOption = Annotated[
    bool, typer.Option("--reveal-hidden", help="raise the file count to what the side holds")
]
DropOption = Annotated[
    bool, typer.Option("--drop-hidden", help="remove files past the declared count")
]
RenumberOption = Annotated[bool, typer.Option("--renumber", help="renumber the files in order")]


def _rebuilt(disk: Disk, options: RebuildOptions) -> tuple[Disk, RebuildReport]:
    try:
        return rebuild(disk, options=options)
    except ValueError as error:
        raise fail(str(error)) from error


def rebuild_command(
    image: ImageArgument,
    output: OutputOption,
    *,
    keep_tail: KeepTailOption = False,
    reveal_hidden: RevealOption = False,
    drop_hidden: DropOption = False,
    renumber: RenumberOption = False,
    force: ForceOption = False,
) -> None:
    guard_output(output, force=force)
    disk, _, _, _ = decode_image(image)
    options = RebuildOptions(
        keep_tail=keep_tail, reveal_hidden=reveal_hidden, drop_hidden=drop_hidden, renumber=renumber
    )
    result, report = _rebuilt(disk, options)
    data, _ = encoded_for(result, output)
    output.write_bytes(data)
    for action in report.actions:
        typer.echo(f"side {action.side}: {action.detail}")
    if not report.changed:
        typer.echo("nothing to repair")
    typer.echo(f"wrote {output} ({len(data)} bytes)")


def set_command(
    image: ImageArgument,
    output: OutputOption,
    *,
    edit: Annotated[list[str], typer.Option("--set", help="field=value, repeatable")],
    side: Annotated[int, typer.Option("--side", min=0, help="which side")] = 0,
    force: ForceOption = False,
) -> None:
    disk, _, _, _ = decode_image(image)
    guard_output(output, force=force)

    try:
        edits = dict(parse_edit(item) for item in edit)
        updated, changes = apply_edits(disk, side=side, edits=edits)
    except ValueError as error:
        raise fail(str(error)) from error

    data, _ = encoded_for(updated, output)
    output.write_bytes(data)

    for change in changes:
        typer.echo(f"{change.field}: {change.before} -> {change.after}")
    typer.echo(f"wrote {output} ({len(data)} bytes)")


def build(
    manifest: Annotated[
        Path, typer.Argument(help="a JSON manifest, or a zip of it with the files it names")
    ],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the image")],
    *,
    force: ForceOption = False,
) -> None:
    if not manifest.is_file():
        message = f"file not found: {manifest}"
        raise fail(message)
    guard_output(output, force=force)

    try:
        data = (
            build_packaged(manifest.read_bytes())
            if manifest.suffix.lower() == ZIP_SUFFIX
            else build_manifest_file(manifest)
        )
    except ValueError as error:
        raise fail(str(error)) from error

    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes)")


def register(app: typer.Typer) -> None:
    app.command(rich_help_panel=Family.REPAIR, help="Write every file on the disk to a directory.")(
        extract
    )
    app.command(
        name="insert",
        rich_help_panel=Family.REPAIR,
        help="Add a file to a side and write the result.",
    )(insert_command)
    app.command(
        name="patch",
        rich_help_panel=Family.REPAIR,
        help="Apply a patch, whether it was made for the headered or headerless image.",
    )(patch_command)
    app.command(
        name="rebuild",
        rich_help_panel=Family.REPAIR,
        help="Re-emit an image from its parsed model, repairing what can be repaired.",
    )(rebuild_command)
    app.command(
        name="set", rich_help_panel=Family.REPAIR, help="Change fields of a disk information block."
    )(set_command)
    app.command(rich_help_panel=Family.CONTAINER, help="Build a disk image from a manifest.")(build)
