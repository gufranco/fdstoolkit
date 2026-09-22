from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from fdstk import __version__
from fdstk.build.blank import blank_image
from fdstk.build.manifest import build_from_manifest, load_manifest
from fdstk.codecs import fds, qd
from fdstk.codecs.mgd1 import SideFile, join_side_files, split_into_side_files
from fdstk.core.blocks import FileKind
from fdstk.core.canon import canonicalise, digest_string, profile_by_name
from fdstk.core.diagnostics import Diagnostic, Severity, worst_severity
from fdstk.core.disk import Disk, Side
from fdstk.edit.clean import clean_trailing_data
from fdstk.edit.diskinfo import apply_edits, parse_edit
from fdstk.edit.emulator import SaveFormat, extract_save, merge_save
from fdstk.edit.files import FileSpec, extract_files, insert_file
from fdstk.edit.multidisk import merge as merge_disks
from fdstk.edit.multidisk import unmerge as unmerge_disk
from fdstk.edit.rebuild import RebuildOptions, rebuild
from fdstk.edit.recipes import load_recipes
from fdstk.edit.saves import find_save_candidates, normalise_saves
from fdstk.fdskey.card import FirmwareVariant, card_blank
from fdstk.fdskey.lint import lint_card_image
from fdstk.hardware.fdsstick import FdsStick, open_fdsstick
from fdstk.hardware.ports import HardwareFaultError
from fdstk.hardware.session import Grade, WriteRefusedError, dump_repeated, write_verified
from fdstk.hardware.session import dump as dump_disk
from fdstk.hardware.simulation import SimulatedDrive
from fdstk.identify.cache import DatCache
from fdstk.identify.dat import Catalogue, Identification, MatchKind, load_dat
from fdstk.identify.dat import identify as identify_image
from fdstk.identify.hashes import digests_of, side_digests
from fdstk.identify.near import NearMatch, nearest_match, reference_images
from fdstk.identify.provenance import provenance_of
from fdstk.patch.apply import apply_patch
from fdstk.patch.formats import PatchError
from fdstk.quality.consensus import build_consensus, compare_images
from fdstk.quality.explain import Explanation, explain
from fdstk.quality.layout import layout_of
from fdstk.quality.surface import SurfaceTestRefusedError, surface_test
from fdstk.report import as_json, diagnostics_as_data

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Famicom Disk System preservation toolkit.",
)


def _version_callback(value: bool) -> None:
    if not value:
        return
    typer.echo(f"fdstk {__version__}")
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


FDS_SUFFIX = ".fds"
QD_SUFFIX = ".qd"


class Container(StrEnum):
    FDS = "fds"
    QD = "qd"


def _fail(message: str) -> typer.Exit:
    typer.echo(message)
    return typer.Exit(code=1)


def _container_of(path: Path) -> Container:
    suffix = path.suffix.lower()
    if suffix == FDS_SUFFIX:
        return Container.FDS
    if suffix == QD_SUFFIX:
        return Container.QD
    message = f"unknown format for {path.name}, expected a {FDS_SUFFIX} or {QD_SUFFIX} file"
    raise _fail(message)


def _read(path: Path) -> tuple[bytes, Container]:
    if not path.is_file():
        message = f"file not found: {path}"
        raise _fail(message)
    return path.read_bytes(), _container_of(path)


def decode_image(path: Path) -> tuple[Disk, tuple[Diagnostic, ...], bytes, Container]:
    data, container = _read(path)
    decoder = fds.decode if container is Container.FDS else qd.decode
    disk, findings = decoder(data)
    return disk, findings, data, container


def _side_summary(index: int, side: Side) -> dict[str, object]:
    info = side.disk_info
    manufactured = info.manufacturing_date if info else None
    rewritten = info.rewritten_date if info else None
    return {
        "index": index,
        "formatted": side.is_formatted,
        "game_name": info.game_name if info else None,
        "game_version": info.game_version if info else None,
        "side": info.side if info else None,
        "disk_number": info.disk_number if info else None,
        "manufacturing_date": list(manufactured) if manufactured else None,
        "rewritten_date": list(rewritten) if rewritten else None,
        "rewrite_count": info.rewrite_count if info else None,
        "writer_serial": info.writer_serial if info else None,
        "declared_files": side.declared_file_count,
        "files": side.file_count,
        "hidden_files": side.hidden_file_count,
        "data_after_last_block": side.has_data_after_last_block,
    }


def _exit_code(findings: tuple[Diagnostic, ...], *, strict: bool) -> int:
    worst = worst_severity(findings)
    if worst is Severity.ERROR:
        return 1
    if strict and worst is Severity.WARNING:
        return 1
    return 0


def _writer_for(path: Path) -> Callable[[bytes], None]:
    def write(data: bytes) -> None:
        path.write_bytes(data)

    return write


def _guard_output(output: Path, *, force: bool) -> None:
    if output.exists() and not force:
        message = f"{output} exists, pass --force to overwrite"
        raise _fail(message)


@app.command()
def info(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    *,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Describe an image, side by side."""
    disk, findings, data, container = decode_image(image)
    payload: dict[str, object] = {
        "path": str(image),
        "container": str(container),
        "size": len(data),
        "side_count": disk.side_count,
        "header_side_count": disk.header_side_count,
        "sides": [_side_summary(index, side) for index, side in enumerate(disk.sides)],
        "diagnostics": diagnostics_as_data(findings),
    }
    if json_output:
        typer.echo(as_json(payload))
        return

    typer.echo(f"{image.name}: {container} container, {disk.side_count} side(s), {len(data)} bytes")
    for index, side in enumerate(disk.sides):
        summary = _side_summary(index, side)
        name = summary["game_name"] or "unformatted"
        typer.echo(
            f"  side {index}: {name} "
            f"files={summary['files']} hidden={summary['hidden_files']} "
            f"rewrites={summary['rewrite_count']}"
        )
    for finding in findings:
        typer.echo(f"  {finding.render()}")


@app.command()
def ls(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    *,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """List the files on every side."""
    disk, _, _, _ = decode_image(image)
    rows: list[dict[str, object]] = []
    for index, side in enumerate(disk.sides):
        declared = side.declared_file_count or 0
        for position, header in enumerate(side.file_headers):
            rows.append(
                {
                    "side": index,
                    "number": header.number,
                    "id": header.file_id,
                    "name": header.name,
                    "address": header.address,
                    "size": header.size,
                    "kind": header.kind.name.lower(),
                    "hidden": position >= declared,
                }
            )

    if json_output:
        typer.echo(as_json({"path": str(image), "files": rows}))
        return

    for row in rows:
        marker = " (hidden)" if row["hidden"] else ""
        typer.echo(
            f"side {row['side']} #{row['number']:3} {row['name']!s:<8} "
            f"{row['kind']:<9} {row['size']:>6} bytes at ${row['address']:04X}{marker}"
        )


@app.command()
def verify(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    *,
    strict: Annotated[bool, typer.Option("--strict", help="treat warnings as failures")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Check an image and report every finding."""
    _, findings, _, _ = decode_image(image)
    code = _exit_code(findings, strict=strict)

    if json_output:
        typer.echo(
            as_json(
                {
                    "path": str(image),
                    "ok": code == 0,
                    "worst_severity": str(worst_severity(findings)),
                    "diagnostics": diagnostics_as_data(findings),
                }
            )
        )
    else:
        for finding in findings:
            typer.echo(finding.render())
        typer.echo("ok" if code == 0 else "failed")

    raise typer.Exit(code=code)


@app.command(name="hash")
def hash_command(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    *,
    profile: Annotated[str, typer.Option("--profile", help="canonical profile")] = "content",
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Hash an image, every side, and its canonical form."""
    disk, _, data, container = decode_image(image)
    side_size = fds.SIDE_SIZE if container is Container.FDS else qd.SIDE_SIZE
    try:
        canonical = canonicalise(disk, profile_by_name(profile))
    except ValueError as error:
        raise _fail(str(error)) from error

    whole = digests_of(data)
    payload: dict[str, object] = {
        "path": str(image),
        "image": whole.as_dict(),
        "headerless": whole.headerless.as_dict() if whole.headerless else None,
        "sides": [entry.as_dict() for entry in side_digests(data, side_size)],
        "canonical": digest_string(canonical),
    }

    if json_output:
        typer.echo(as_json(payload))
        return

    typer.echo(f"size      {whole.size}")
    typer.echo(f"crc32     {whole.crc32}")
    typer.echo(f"md5       {whole.md5}")
    typer.echo(f"sha1      {whole.sha1}")
    typer.echo(f"sha256    {whole.sha256}")
    typer.echo(f"canonical {digest_string(canonical)}")


@app.command()
def convert(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write")],
    *,
    header: Annotated[
        bool,
        typer.Option("--header/--no-header", help="write an fwNES header"),
    ] = False,
    crc_mode: Annotated[
        qd.CrcMode,
        typer.Option("--crc-mode", help="CRC handling when writing a .qd"),
    ] = qd.CrcMode.PRESERVE,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Convert between .fds and .qd."""
    disk, _, _, _ = decode_image(image)
    target = _container_of(output)
    _guard_output(output, force=force)

    if target is Container.FDS:
        data, findings = fds.encode(disk, headered=header)
    else:
        data, findings = qd.encode(disk, crc_mode=crc_mode)

    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    for finding in findings:
        typer.echo(f"  {finding.render()}")
    if worst_severity(findings) is Severity.ERROR:
        raise typer.Exit(code=1)


@app.command()
def canon(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    *,
    profile: Annotated[str, typer.Option("--profile", help="raw, content or data")] = "content",
    output: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="write the canonical image"),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Print the canonical digest, and optionally write the canonical image."""
    disk, _, _, _ = decode_image(image)
    try:
        result = canonicalise(disk, profile_by_name(profile))
    except ValueError as error:
        raise _fail(str(error)) from error

    typer.echo(digest_string(result))
    if output is None:
        return
    _guard_output(output, force=force)
    output.write_bytes(result.data)
    typer.echo(f"wrote {output} ({len(result.data)} bytes)")


@app.command()
def blank(
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write")],
    *,
    sides: Annotated[int, typer.Option("--sides", min=1, max=8, help="side count")] = 1,
    formatted: Annotated[bool, typer.Option("--formatted", help="write a disk info block")] = False,
    header: Annotated[bool, typer.Option("--header", help="write an fwNES header")] = False,
    game_name: Annotated[str, typer.Option("--game-name", help="three-character code")] = "   ",
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Create a blank image."""
    _guard_output(output, force=force)
    try:
        data = blank_image(
            sides=sides,
            headered=header,
            formatted=formatted,
            game_name=game_name,
        )
    except ValueError as error:
        raise _fail(str(error)) from error
    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes)")


@app.command()
def lint(
    image: Annotated[Path, typer.Argument(help="a .fds image destined for an FDSKey card")],
    *,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Predict whether FDSKey will load an image, before it reaches the card."""
    data, _ = _read(image)
    findings = lint_card_image(data, name=image)

    if json_output:
        typer.echo(
            as_json(
                {
                    "path": str(image),
                    "ok": not findings,
                    "findings": [
                        {
                            "code": finding.code,
                            "message": finding.message,
                            "side": finding.side,
                            "detail": dict(sorted(finding.detail.items())),
                        }
                        for finding in findings
                    ],
                }
            )
        )
    else:
        for finding in findings:
            where = "" if finding.side is None else f"side {finding.side}: "
            typer.echo(f"{where}[{finding.code}] {finding.message}")
        typer.echo("ok" if not findings else "would not load")

    raise typer.Exit(code=0 if not findings else 1)


class Backend(StrEnum):
    SIMULATION = "simulation"
    FDSSTICK = "fdsstick"
    DUMPER = "dumper"


def open_drive(backend: Backend, source: Path | None) -> SimulatedDrive | FdsStick:
    if backend is Backend.DUMPER:
        message = (
            "the Famicom Dumper backend needs a serial link, which this build does not open yet. "
            "Use --backend fdsstick, or drive it from the library with your own link"
        )
        raise _fail(message)
    if backend is Backend.FDSSTICK:
        try:
            return open_fdsstick()
        except HardwareFaultError as error:
            raise _fail(str(error)) from error
    if source is None:
        message = "the simulated backend needs --source naming an image to stand in for the disk"
        raise _fail(message)
    disk, _, _, _ = decode_image(source)
    return SimulatedDrive(disk)


@app.command()
def dump(
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the dump")],
    *,
    source: Annotated[
        Path | None,
        typer.Option("--source", help="image the simulated drive holds"),
    ] = None,
    backend: Annotated[
        Backend, typer.Option("--backend", help="which drive to use")
    ] = Backend.SIMULATION,
    sides: Annotated[int, typer.Option("--sides", min=1, max=8, help="sides to read")] = 1,
    passes: Annotated[int, typer.Option("--passes", min=1, help="read each side this often")] = 1,
    retries: Annotated[int, typer.Option("--retries", min=1, help="retries per block")] = 3,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Dump a disk through a drive backend."""
    _guard_output(output, force=force)
    drive = open_drive(backend, source)

    try:
        if passes > 1:
            report = dump_repeated(drive, sides=sides, passes=passes, retries=retries)
            result = report.passes[0]
            grade = report.grade
            for side_index, block_index in report.unstable_blocks:
                typer.echo(f"side {side_index}: block {block_index} differs between passes")
        else:
            result = dump_disk(drive, sides=sides, retries=retries)
            grade = result.grade
    except KeyboardInterrupt:
        message = "stopped on interrupt, nothing was written"
        raise _fail(message) from None
    except (HardwareFaultError, WriteRefusedError) as error:
        raise _fail(str(error)) from error

    data, _ = fds.encode(result.as_disk(), headered=False)
    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes), grade {grade}")
    raise typer.Exit(code=0 if grade is Grade.CLEAN else 1)


@app.command()
def write(
    image: Annotated[Path, typer.Argument(help="the image to write to a disk")],
    *,
    source: Annotated[
        Path | None,
        typer.Option("--source", help="image the simulated drive holds"),
    ] = None,
    backend: Annotated[
        Backend, typer.Option("--backend", help="which drive to use")
    ] = Backend.SIMULATION,
    backup: Annotated[
        Path | None,
        typer.Option("--backup", help="where to save the disk's current contents"),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", help="answer the confirmation")] = False,
    retries: Annotated[int, typer.Option("--retries", min=1, help="retries per block")] = 3,
) -> None:
    """Write an image to a disk, then read it back and compare."""
    disk, _, _, _ = decode_image(image)
    drive = open_drive(backend, source)

    def confirm(message: str) -> bool:
        if yes:
            return True
        return typer.confirm(message)

    try:
        report = write_verified(
            drive,
            drive,
            disk,
            confirm=confirm,
            backup=None if backup is None else _writer_for(backup),
            retries=retries,
        )
    except KeyboardInterrupt:
        message = "stopped on interrupt, the disk may be half written, dump it before using it"
        raise _fail(message) from None
    except (HardwareFaultError, WriteRefusedError) as error:
        raise _fail(str(error)) from error

    for side_index, block_index in report.mismatched_blocks:
        typer.echo(f"side {side_index}: block {block_index} did not read back as written")
    typer.echo(f"verified {report.verified}, grade {report.grade}")
    raise typer.Exit(code=0 if report.verified else 1)


@app.command()
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
    data, _ = _read(image)
    try:
        catalogue, cached = _catalogue(dat, no_cache=no_cache)
    except ValueError as error:
        raise _fail(str(error)) from error

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


@app.command()
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
            raise _fail(message)
        target.write_bytes(entry.data)
        marker = " (hidden)" if entry.hidden else ""
        typer.echo(f"{target.name}  {entry.size} bytes{marker}")


@app.command(name="insert")
def insert_command(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the result")],
    *,
    file: Annotated[Path, typer.Option("--file", help="the file to add")],
    name: Annotated[str, typer.Option("--name", help="eight characters at most")],
    address: Annotated[str, typer.Option("--address", help="load address, hex")] = "6000",
    kind: Annotated[
        FileKind, typer.Option("--kind", help="program, character or nametable")
    ] = FileKind.PROGRAM,
    side: Annotated[int, typer.Option("--side", min=0, help="which side")] = 0,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Add a file to a side and write the result."""
    disk, _, _, _ = decode_image(image)
    _guard_output(output, force=force)
    if not file.is_file():
        message = f"file not found: {file}"
        raise _fail(message)

    try:
        spec = FileSpec(
            name=name,
            address=int(address, 16),
            kind=kind,
            data=file.read_bytes(),
        )
        updated = insert_file(disk, side=side, spec=spec)
    except ValueError as error:
        raise _fail(str(error)) from error

    target = _container_of(output)
    if target is Container.FDS:
        data, findings = fds.encode(updated, headered=False)
    else:
        data, findings = qd.encode(updated)

    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    for finding in findings:
        typer.echo(f"  {finding.render()}")


@app.command(name="patch")
def patch_command(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    patch_file: Annotated[Path, typer.Option("--patch", help="an IPS, UPS or BPS patch")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the result")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Apply a patch, whether it was made for the headered or headerless image."""
    data, _ = _read(image)
    if not patch_file.is_file():
        message = f"file not found: {patch_file}"
        raise _fail(message)
    _guard_output(output, force=force)

    try:
        outcome = apply_patch(patch_file.read_bytes(), data)
    except PatchError as error:
        raise _fail(str(error)) from error

    output.write_bytes(outcome.data)
    typer.echo(
        f"applied {outcome.format} patch to the {outcome.applied_to}, "
        f"wrote {output} ({len(outcome.data)} bytes)"
    )


@app.command()
def provenance(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    *,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Report where each side came from: factory, kiosk rewrite, or unknown."""
    disk, _, _, _ = decode_image(image)
    report = provenance_of(disk)

    if json_output:
        typer.echo(
            as_json({"path": str(image), "sides": [side.as_dict() for side in report.sides]})
        )
        return

    for side in report.sides:
        typer.echo(
            f"side {side.index}: {side.origin} "
            f"made {side.manufacturing_date} rewritten {side.rewritten_date} "
            f"count {side.rewrite_count} writer {side.writer_serial}"
        )
        for note in side.notes:
            typer.echo(f"  {note}")


@app.command()
def saves(
    images: Annotated[list[Path], typer.Argument(help="two or more dumps of the same release")],
    *,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Compare dumps of one release and report which file looks like the save."""
    disks = [decode_image(path)[0] for path in images]
    try:
        candidates = find_save_candidates(disks)
    except ValueError as error:
        raise _fail(str(error)) from error

    if json_output:
        typer.echo(
            as_json(
                {
                    "images": [str(path) for path in images],
                    "candidates": [
                        {
                            "side": candidate.side,
                            "position": candidate.position,
                            "name": candidate.name,
                            "size": candidate.size,
                            "differing_bytes": candidate.differing_bytes,
                            "name_matches_pattern": candidate.name_matches_pattern,
                        }
                        for candidate in candidates
                    ],
                }
            )
        )
        return

    if not candidates:
        typer.echo("no save candidate: every file agrees across the dumps")
        return
    for candidate in candidates:
        marker = ", name reads like a save" if candidate.name_matches_pattern else ""
        typer.echo(
            f"side {candidate.side} file {candidate.position} {candidate.name}: "
            f"{candidate.differing_bytes} of {candidate.size} bytes differ{marker}"
        )


@app.command()
def clean(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the result")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Remove leftover bytes after the last block of every side."""
    disk, _, _, _ = decode_image(image)
    _guard_output(output, force=force)

    cleaned, removed = clean_trailing_data(disk)
    target = _container_of(output)
    if target is Container.FDS:
        data, _ = fds.encode(cleaned, headered=False)
    else:
        data, _ = qd.encode(cleaned)
    output.write_bytes(data)

    for entry in removed:
        typer.echo(f"side {entry.side}: removed {entry.bytes_removed} trailing byte(s)")
    typer.echo(f"wrote {output} ({len(data)} bytes)")


@app.command(name="diff")
def diff_command(
    first: Annotated[Path, typer.Argument(help="the first image")],
    second: Annotated[Path, typer.Argument(help="the second image")],
    *,
    explain_fields: Annotated[
        bool, typer.Option("--explain", help="name the fields and files that differ")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Compare two images block by block."""
    left, _, _, _ = decode_image(first)
    right, _, _, _ = decode_image(second)
    report = compare_images(left, right)

    if explain_fields:
        _print_explanation(first, second, explain(left, right), json_output=json_output)
        raise typer.Exit(code=0 if report.identical else 1)

    if json_output:
        typer.echo(
            as_json(
                {
                    "first": str(first),
                    "second": str(second),
                    "identical": report.identical,
                    "summary": report.summary,
                    "differing_blocks": [list(pair) for pair in report.differing_blocks],
                }
            )
        )
    else:
        typer.echo(report.summary)
        for side_index, block_index in report.differing_blocks:
            typer.echo(f"  side {side_index} block {block_index}")

    raise typer.Exit(code=0 if report.identical else 1)


def _print_explanation(
    first: Path, second: Path, result: Explanation, *, json_output: bool
) -> None:
    if json_output:
        typer.echo(
            as_json(
                {
                    "first": str(first),
                    "second": str(second),
                    "identical": result.identical,
                    "same_software": result.same_software,
                    "headline": result.headline,
                    "fields": [
                        {
                            "side": entry.side,
                            "field": entry.field,
                            "description": entry.description,
                            "identity": entry.identity,
                            "first": entry.left,
                            "second": entry.right,
                        }
                        for entry in result.fields
                    ],
                    "files": [
                        {
                            "side": entry.side,
                            "position": entry.position,
                            "name": entry.name,
                            "change": str(entry.change),
                            "detail": entry.detail,
                        }
                        for entry in result.files
                    ],
                }
            )
        )
        return

    typer.echo(result.headline)
    for entry in result.fields:
        marker = "identity" if entry.identity else "provenance"
        typer.echo(
            f"  side {entry.side} {entry.field} ({marker}): {entry.left} against {entry.right}"
        )
    for entry in result.files:
        typer.echo(
            f"  side {entry.side} file {entry.position} {entry.name}: "
            f"{entry.change}, {entry.detail}"
        )


@app.command(name="rebuild")
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
    _guard_output(output, force=force)
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
        raise _fail(str(error)) from error

    if _container_of(output) is Container.FDS:
        data, _ = fds.encode(result, headered=False)
    else:
        data, _ = qd.encode(result)
    output.write_bytes(data)

    for action in report.actions:
        typer.echo(f"side {action.side}: {action.detail}")
    if not report.changed:
        typer.echo("nothing to repair")
    typer.echo(f"wrote {output} ({len(data)} bytes)")


@app.command(name="dat-cache")
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


@app.command()
def layout(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    *,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Show where each file sits on the side, and what it costs to reach it."""
    disk, _, _, _ = decode_image(image)
    report = layout_of(disk)

    if json_output:
        typer.echo(
            as_json(
                {
                    "path": str(image),
                    "dead_bytes": report.dead_bytes,
                    "sides": [
                        {
                            "side": side.side,
                            "stream_bytes": side.stream_bytes,
                            "seconds_to_read": round(side.seconds_to_read, 4),
                            "dead_bytes": side.dead_bytes,
                            "reorder_saving_bytes": side.reorder_saving_bytes,
                            "note": side.note,
                            "files": [
                                {
                                    "position": entry.position,
                                    "file_id": entry.file_id,
                                    "name": entry.name,
                                    "size": entry.size,
                                    "offset": entry.offset,
                                    "seconds_to_reach": round(entry.seconds_to_reach, 4),
                                    "hidden": entry.hidden,
                                }
                                for entry in side.placements
                            ],
                        }
                        for side in report.sides
                    ],
                }
            )
        )
        raise typer.Exit(code=0)

    for side in report.sides:
        typer.echo(
            f"side {side.side}: {side.stream_bytes} bytes of stream, "
            f"{side.seconds_to_read:.2f}s to read end to end"
        )
        for entry in side.placements:
            marker = " (hidden)" if entry.hidden else ""
            typer.echo(
                f"  {entry.position:2d} {entry.name:<8} id {entry.file_id:3d}  "
                f"{entry.size:6d} bytes  reached at {entry.seconds_to_reach:5.2f}s{marker}"
            )
        if side.dead_bytes:
            typer.echo(f"  {side.dead_bytes} byte(s) of dead weight after the last block")
        if side.note:
            typer.echo(f"  {side.note}")


@app.command()
def merge(
    images: Annotated[list[Path], typer.Argument(help="the disks of one set, in order")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the set")],
    *,
    header: Annotated[
        bool, typer.Option("--header/--no-header", help="write an fwNES header")
    ] = False,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Join the disks of a multi-disk game into one image."""
    _guard_output(output, force=force)
    disks = [decode_image(path)[0] for path in images]

    try:
        merged, findings = merge_disks(disks)
    except ValueError as error:
        raise _fail(str(error)) from error

    if _container_of(output) is Container.FDS:
        data, encoding = fds.encode(merged, headered=header)
    else:
        data, encoding = qd.encode(merged)
    output.write_bytes(data)

    for finding in (*findings, *encoding):
        typer.echo(f"  {finding.render()}")
    typer.echo(f"wrote {output} ({merged.side_count} sides, {len(data)} bytes)")


@app.command()
def unmerge(
    image: Annotated[Path, typer.Argument(help="a merged multi-disk image")],
    directory: Annotated[Path, typer.Option("-d", "--directory", help="where to write the disks")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite existing files")] = False,
) -> None:
    """Split a merged multi-disk image back into one file per disk."""
    disk, _, _, container = decode_image(image)
    parts, findings = unmerge_disk(disk)
    directory.mkdir(parents=True, exist_ok=True)

    for finding in findings:
        typer.echo(f"  {finding.render()}")

    suffix = FDS_SUFFIX if container is Container.FDS else QD_SUFFIX
    for index, part in enumerate(parts, start=1):
        target = directory / f"{image.stem} (Disk {index}){suffix}"
        if target.exists() and not force:
            message = f"{target} exists, pass --force to overwrite"
            raise _fail(message)
        if container is Container.FDS:
            data, _ = fds.encode(part, headered=part.header_side_count is not None)
        else:
            data, _ = qd.encode(part)
        target.write_bytes(data)
        typer.echo(f"{target.name}  {part.side_count} side(s), {len(data)} bytes")


@app.command()
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
    _guard_output(output, force=force)
    disks = [decode_image(path)[0] for path in images]

    try:
        result = build_consensus(disks)
    except ValueError as error:
        raise _fail(str(error)) from error

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


@app.command(name="save-apply")
def save_apply(
    image: Annotated[Path, typer.Argument(help="the original image")],
    save: Annotated[Path, typer.Option("--save", help="an emulator save, IPS or whole image")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the result")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Merge an emulator save back into a disk image."""
    data, _ = _read(image)
    if not save.is_file():
        message = f"file not found: {save}"
        raise _fail(message)
    _guard_output(output, force=force)

    try:
        merged = merge_save(data, save.read_bytes())
    except PatchError as error:
        raise _fail(str(error)) from error

    output.write_bytes(merged)
    typer.echo(f"wrote {output} ({len(merged)} bytes)")


@app.command(name="save-extract")
def save_extract(
    original_image: Annotated[Path, typer.Argument(help="the pristine image")],
    played: Annotated[Path, typer.Option("--played", help="the image a game wrote to")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the save")],
    *,
    fmt: Annotated[SaveFormat, typer.Option("--format", help="ips or image")] = SaveFormat.IPS,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Write the difference between a pristine disk and a played one as a save."""
    pristine, _ = _read(original_image)
    if not played.is_file():
        message = f"file not found: {played}"
        raise _fail(message)
    _guard_output(output, force=force)

    try:
        save = extract_save(pristine, played.read_bytes(), fmt=fmt)
    except PatchError as error:
        raise _fail(str(error)) from error

    output.write_bytes(save)
    typer.echo(f"wrote {output} ({len(save)} bytes, {fmt})")


@app.command()
def card(
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the blank")],
    *,
    sides: Annotated[int, typer.Option("--sides", min=1, max=8, help="side count")] = 1,
    variant: Annotated[
        FirmwareVariant,
        typer.Option("--firmware", help="released accepts an all-zero blank, master does not"),
    ] = FirmwareVariant.MASTER,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Write a blank image an FDSKey card will accept."""
    _guard_output(output, force=force)
    data = card_blank(sides=sides, variant=variant)
    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes, for {variant} firmware)")


@app.command()
def split(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    directory: Annotated[Path, typer.Option("-d", "--directory", help="where to write the sides")],
    *,
    stem: Annotated[str, typer.Option("--stem", help="base name for the side files")] = "fc1234",
    force: Annotated[bool, typer.Option("--force", help="overwrite existing files")] = False,
) -> None:
    """Split an image into one file per side, the way a Game Doctor stores it."""
    data, _ = _read(image)
    directory.mkdir(parents=True, exist_ok=True)

    for entry in split_into_side_files(data, stem=stem):
        target = directory / entry.name
        if target.exists() and not force:
            message = f"{target} exists, pass --force to overwrite"
            raise _fail(message)
        target.write_bytes(entry.data)
        typer.echo(f"{entry.name}  {len(entry.data)} bytes")


@app.command()
def join(
    files: Annotated[list[Path], typer.Argument(help="the side files, in any order")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the image")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Join per-side files back into one image."""
    _guard_output(output, force=force)
    sides: list[SideFile] = []
    for path in files:
        if not path.is_file():
            message = f"file not found: {path}"
            raise _fail(message)
        sides.append(SideFile(name=path.name, data=path.read_bytes()))

    try:
        data = join_side_files(sides)
    except ValueError as error:
        raise _fail(str(error)) from error

    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes)")


@app.command()
def build(
    manifest: Annotated[Path, typer.Argument(help="a JSON manifest describing the disk")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the image")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Build a disk image from a manifest."""
    if not manifest.is_file():
        message = f"file not found: {manifest}"
        raise _fail(message)
    _guard_output(output, force=force)

    try:
        data = build_from_manifest(load_manifest(manifest))
    except ValueError as error:
        raise _fail(str(error)) from error

    output.write_bytes(data)
    typer.echo(f"wrote {output} ({len(data)} bytes)")


@app.command(name="set")
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
    _guard_output(output, force=force)

    try:
        edits = dict(parse_edit(item) for item in edit)
        updated, changes = apply_edits(disk, side=side, edits=edits)
    except ValueError as error:
        raise _fail(str(error)) from error

    target = _container_of(output)
    if target is Container.FDS:
        data, _ = fds.encode(updated, headered=False)
    else:
        data, _ = qd.encode(updated)
    output.write_bytes(data)

    for change in changes:
        typer.echo(f"{change.field}: {change.before} -> {change.after}")
    typer.echo(f"wrote {output} ({len(data)} bytes)")


@app.command()
def surface(
    *,
    source: Annotated[
        Path | None,
        typer.Option("--source", help="image the simulated drive holds"),
    ] = None,
    backend: Annotated[
        Backend,
        typer.Option("--backend", help="which drive to use"),
    ] = Backend.SIMULATION,
    sides: Annotated[int, typer.Option("--sides", min=1, max=8, help="sides to test")] = 1,
    backup: Annotated[
        Path | None,
        typer.Option("--backup", help="where to save the disk's current contents"),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", help="answer the confirmation")] = False,
) -> None:
    """Write and read back complementary patterns to grade a scratch disk."""
    drive = open_drive(backend, source)

    def confirm(message: str) -> bool:
        if yes:
            return True
        return typer.confirm(message)

    sink = None if backup is None else _writer_for(backup)

    try:
        report = surface_test(
            drive,
            drive,
            sides=sides,
            confirm=confirm,
            backup=sink,
        )
    except (HardwareFaultError, WriteRefusedError, SurfaceTestRefusedError) as error:
        raise _fail(str(error)) from error

    for entry in report.passes:
        state = "held" if entry.verified else "did not hold"
        typer.echo(f"pattern {entry.pattern:#04x}: {state}")
    typer.echo(f"grade {report.grade}")
    raise typer.Exit(code=0 if report.grade is Grade.CLEAN else 1)


@app.command(name="normalise-saves")
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
        raise _fail(message)
    _guard_output(output, force=force)

    try:
        updated, applied = normalise_saves(disk, load_recipes(recipes))
    except ValueError as error:
        raise _fail(str(error)) from error

    target = _container_of(output)
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
