from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import (
    Container,
    Family,
    decode_image,
    exit_code,
    fail,
    guard_output,
    side_summary,
)
from fdstoolkit.codecs import fds, qd
from fdstoolkit.core.bios import BootVerdict, predict_boot
from fdstoolkit.core.canon import canonicalise, digest_string, profile_by_name
from fdstoolkit.core.diagnostics import worst_severity
from fdstoolkit.core.disk import Disk
from fdstoolkit.doctor import CheckStatus, diagnose
from fdstoolkit.identify.hashes import digests_of, retroachievements_hash, side_digests
from fdstoolkit.identify.provenance import provenance_of
from fdstoolkit.report import as_json, diagnostics_as_data


def file_rows(disk: Disk) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, side in enumerate(disk.sides):
        declared = side.declared_file_count or 0
        rows.extend(
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
            for position, header in enumerate(side.file_headers)
        )
    return rows


def info(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    *,
    files: Annotated[
        bool, typer.Option("--files", help="also list every file on every side")
    ] = False,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Describe an image, side by side, and with --files every file on it."""
    disk, findings, data, container = decode_image(image)
    payload: dict[str, object] = {
        "path": str(image),
        "container": str(container),
        "size": len(data),
        "side_count": disk.side_count,
        "header_side_count": disk.header_side_count,
        "sides": [side_summary(index, side) for index, side in enumerate(disk.sides)],
        "diagnostics": diagnostics_as_data(findings),
    }
    if files:
        payload["files"] = file_rows(disk)
    if json_output:
        typer.echo(as_json(payload))
        return

    typer.echo(f"{image.name}: {container} container, {disk.side_count} side(s), {len(data)} bytes")
    for index, side in enumerate(disk.sides):
        summary = side_summary(index, side)
        name = summary["game_name"] or "unformatted"
        typer.echo(
            f"  side {index}: {name} "
            f"files={summary['files']} hidden={summary['hidden_files']} "
            f"rewrites={summary['rewrite_count']}"
        )
    for finding in findings:
        typer.echo(f"  {finding.render()}")
    if not files:
        return
    for row in file_rows(disk):
        marker = " (hidden)" if row["hidden"] else ""
        typer.echo(
            f"side {row['side']} #{row['number']:3} {row['name']!s:<8} "
            f"{row['kind']:<9} {row['size']:>6} bytes at ${row['address']:04X}{marker}"
        )


def verify(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    *,
    strict: Annotated[bool, typer.Option("--strict", help="treat warnings as failures")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Check an image and report every finding."""
    _, findings, _, _ = decode_image(image)
    code = exit_code(findings, strict=strict)

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


def hash_command(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    *,
    profile: Annotated[str, typer.Option("--profile", help="raw, content or data")] = "content",
    output: Annotated[
        Path | None,
        typer.Option("-o", "--output", help="also write the canonical image"),
    ] = None,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Hash an image, every side, and its canonical form, which -o also writes out."""
    disk, _, data, container = decode_image(image)
    side_size = fds.SIDE_SIZE if container is Container.FDS else qd.SIDE_SIZE
    try:
        canonical = canonicalise(disk, profile_by_name(profile))
    except ValueError as error:
        raise fail(str(error)) from error
    if output is not None:
        guard_output(output, force=force)
        output.write_bytes(canonical.data)

    whole = digests_of(data)
    payload: dict[str, object] = {
        "path": str(image),
        "image": whole.as_dict(),
        "headerless": whole.headerless.as_dict() if whole.headerless else None,
        "sides": [entry.as_dict() for entry in side_digests(data, side_size)],
        "canonical": digest_string(canonical),
        "retroachievements": retroachievements_hash(data),
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
    typer.echo(f"ra md5    {retroachievements_hash(data)}")
    if output is not None:
        typer.echo(f"wrote {output} ({len(canonical.data)} bytes)")


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


def boot(
    image: Annotated[Path, typer.Argument(help="a .fds or .qd image")],
    *,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Predict what the console does when it boots each side."""
    disk, _, _, _ = decode_image(image)
    report = predict_boot(disk)

    if json_output:
        typer.echo(
            as_json(
                {
                    "path": str(image),
                    "sides": [
                        {
                            "side": side.side,
                            "verdict": str(side.verdict),
                            "error": side.error,
                            "message": side.message,
                            "boot_files": [
                                {
                                    "position": entry.position,
                                    "file_id": entry.file_id,
                                    "name": entry.name,
                                    "address": entry.address,
                                    "size": entry.size,
                                }
                                for entry in side.boot_files
                            ],
                        }
                        for side in report.sides
                    ],
                }
            )
        )
    else:
        for side in report.sides:
            typer.echo(f"side {side.side}: {side.message}")
            for entry in side.boot_files:
                typer.echo(
                    f"  loads #{entry.position} id {entry.file_id} {entry.name!r} "
                    f"{entry.size} bytes at ${entry.address:04X}"
                )

    failed = any(side.verdict is BootVerdict.FAILS for side in report.sides[:1])
    raise typer.Exit(code=1 if failed else 0)


def doctor(
    *,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Check the installation: version, Python and hardware support."""
    report = diagnose()
    if json_output:
        typer.echo(
            as_json(
                {
                    "healthy": report.healthy,
                    "checks": [
                        {"name": check.name, "status": str(check.status), "detail": check.detail}
                        for check in report.checks
                    ],
                }
            )
        )
    else:
        for check in report.checks:
            marker = "" if check.status is CheckStatus.OK else f" [{check.status}]"
            typer.echo(f"{check.name:<17} {check.detail}{marker}")
    raise typer.Exit(code=0 if report.healthy else 1)


def register(app: typer.Typer) -> None:
    app.command(rich_help_panel=Family.INSPECT)(info)
    app.command(rich_help_panel=Family.CHECK)(verify)
    app.command(name="hash", rich_help_panel=Family.INSPECT)(hash_command)
    app.command(rich_help_panel=Family.INSPECT)(provenance)
    app.command(rich_help_panel=Family.INSPECT)(boot)
    app.command(rich_help_panel=Family.HARDWARE)(doctor)
