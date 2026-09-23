from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.cli.common import (
    Container,
    decode_image,
    exit_code,
    fail,
    read_image,
    side_summary,
)
from fdstoolkit.codecs import fds, qd
from fdstoolkit.core.bios import BootVerdict, predict_boot
from fdstoolkit.core.canon import canonicalise, digest_string, profile_by_name
from fdstoolkit.core.diagnostics import worst_severity
from fdstoolkit.doctor import CheckStatus, diagnose
from fdstoolkit.fdskey.lint import lint_card_image
from fdstoolkit.identify.hashes import digests_of, retroachievements_hash, side_digests
from fdstoolkit.identify.provenance import provenance_of
from fdstoolkit.quality.layout import layout_of
from fdstoolkit.report import as_json, diagnostics_as_data


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
        "sides": [side_summary(index, side) for index, side in enumerate(disk.sides)],
        "diagnostics": diagnostics_as_data(findings),
    }
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
    profile: Annotated[str, typer.Option("--profile", help="canonical profile")] = "content",
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Hash an image, every side, and its canonical form."""
    disk, _, data, container = decode_image(image)
    side_size = fds.SIDE_SIZE if container is Container.FDS else qd.SIDE_SIZE
    try:
        canonical = canonicalise(disk, profile_by_name(profile))
    except ValueError as error:
        raise fail(str(error)) from error

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


def lint(
    image: Annotated[Path, typer.Argument(help="a .fds image destined for an FDSKey card")],
    *,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Predict whether FDSKey will load an image, before it reaches the card."""
    data, _ = read_image(image)
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


def doctor(
    *,
    json_output: Annotated[bool, typer.Option("--json", help="emit JSON")] = False,
) -> None:
    """Check the installation: version, Python, hardware support and caches."""
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
    app.command()(info)
    app.command()(ls)
    app.command()(verify)
    app.command(name="hash")(hash_command)
    app.command()(provenance)
    app.command()(layout)
    app.command()(boot)
    app.command()(lint)
    app.command()(doctor)
