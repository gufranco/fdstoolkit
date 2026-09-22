from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from fdstk.build.blank import blank_image
from fdstk.codecs import fds, qd
from fdstk.core.canon import canonicalise, digest_string, profile_by_name
from fdstk.core.diagnostics import Diagnostic, Severity, worst_severity
from fdstk.core.disk import Disk, Side
from fdstk.identify.hashes import digests_of, side_digests
from fdstk.report import as_json, diagnostics_as_data

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Famicom Disk System preservation toolkit.",
)

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


def _decode(path: Path) -> tuple[Disk, tuple[Diagnostic, ...], bytes, Container]:
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
    disk, findings, data, container = _decode(image)
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
    disk, _, _, _ = _decode(image)
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
    _, findings, _, _ = _decode(image)
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
    disk, _, data, container = _decode(image)
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
    disk, _, _, _ = _decode(image)
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
    disk, _, _, _ = _decode(image)
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
