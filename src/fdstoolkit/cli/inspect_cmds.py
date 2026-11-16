from __future__ import annotations

from pathlib import Path
from typing import Annotated, Final

import typer

from fdstoolkit.cli.common import (
    Family,
    ForceOption,
    ImageArgument,
    JsonOption,
    decode_image,
    exit_code,
    fail,
    guard_output,
    load_captures,
    side_summary,
)
from fdstoolkit.codecs import qd
from fdstoolkit.codecs.container import Container
from fdstoolkit.core.bios import BootReport, BootVerdict, SideBoot, predict_boot
from fdstoolkit.core.canon import CanonResult, canonicalise, digest_string, profile_by_name
from fdstoolkit.core.diagnostics import worst_severity
from fdstoolkit.core.disk import SIDE_SIZE, Disk
from fdstoolkit.core.diskinfo import PROFILES
from fdstoolkit.doctor import CheckStatus, diagnose
from fdstoolkit.identify.hashes import digests_of, retroachievements_hash, side_digests
from fdstoolkit.identify.layout import LayoutReading, layouts_for
from fdstoolkit.identify.provenance import provenance_of
from fdstoolkit.report import as_json, diagnostics_as_data

PROFILE_HELP: Final = f"one of {', '.join(sorted(PROFILES))}"


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


FilesOption = Annotated[bool, typer.Option("--files", help="also list every file on every side")]


def _print_sides(disk: Disk) -> None:
    for index, side in enumerate(disk.sides):
        summary = side_summary(index, side)
        name = summary["game_name"] or "unformatted"
        typer.echo(
            f"  side {index}: {name} "
            f"files={summary['files']} hidden={summary['hidden_files']} "
            f"rewrites={summary['rewrite_count']}"
        )


def _print_files(disk: Disk) -> None:
    for row in file_rows(disk):
        marker = " (hidden)" if row["hidden"] else ""
        typer.echo(
            f"side {row['side']} #{row['number']:3} {row['name']!s:<8} "
            f"{row['kind']:<9} {row['size']:>6} bytes at ${row['address']:04X}{marker}"
        )


def info(
    image: ImageArgument, *, files: FilesOption = False, json_output: JsonOption = False
) -> None:
    disk, findings, data, container = decode_image(image)
    if json_output:
        payload: dict[str, object] = {
            "path": str(image),
            "container": str(container),
            "size": len(data),
            "side_count": disk.side_count,
            "header_side_count": disk.header_side_count,
            "sides": [side_summary(index, side) for index, side in enumerate(disk.sides)],
            "diagnostics": diagnostics_as_data(findings),
        }
        typer.echo(as_json({**payload, **({"files": file_rows(disk)} if files else {})}))
        return
    typer.echo(f"{image.name}: {container} container, {disk.side_count} side(s), {len(data)} bytes")
    _print_sides(disk)
    for finding in findings:
        typer.echo(f"  {finding.render()}")
    if files:
        _print_files(disk)


def verify(
    image: ImageArgument,
    *,
    strict: Annotated[bool, typer.Option("--strict", help="treat warnings as failures")] = False,
    json_output: JsonOption = False,
) -> None:
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


CanonicalOption = Annotated[
    Path | None, typer.Option("-o", "--output", help="also write the canonical image")
]


def _hash_payload(
    image: Path, data: bytes, side_size: int, canonical: CanonResult
) -> dict[str, object]:
    whole = digests_of(data)
    return {
        "path": str(image),
        "image": whole.as_dict(),
        "headerless": whole.headerless.as_dict() if whole.headerless else None,
        "sides": [entry.as_dict() for entry in side_digests(data, side_size)],
        "canonical": digest_string(canonical),
        "retroachievements": retroachievements_hash(data),
    }


def _print_hashes(data: bytes, canonical: CanonResult) -> None:
    whole = digests_of(data)
    typer.echo(f"size      {whole.size}")
    typer.echo(f"crc32     {whole.crc32}")
    typer.echo(f"md5       {whole.md5}")
    typer.echo(f"sha1      {whole.sha1}")
    typer.echo(f"sha256    {whole.sha256}")
    typer.echo(f"canonical {digest_string(canonical)}")
    typer.echo(f"ra md5    {retroachievements_hash(data)}")


def _canonical(disk: Disk, profile: str) -> CanonResult:
    try:
        return canonicalise(disk, profile_by_name(profile))
    except ValueError as error:
        raise fail(str(error)) from error


def hash_command(
    image: ImageArgument,
    *,
    profile: Annotated[str, typer.Option("--profile", help=PROFILE_HELP)] = "content",
    output: CanonicalOption = None,
    force: ForceOption = False,
    json_output: JsonOption = False,
) -> None:
    disk, _, data, container = decode_image(image)
    side_size = SIDE_SIZE if container is Container.FDS else qd.SIDE_SIZE
    canonical = _canonical(disk, profile)
    if output is not None:
        guard_output(output, force=force)
        output.write_bytes(canonical.data)
    if json_output:
        typer.echo(as_json(_hash_payload(image, data, side_size, canonical)))
        return
    _print_hashes(data, canonical)
    if output is not None:
        typer.echo(f"wrote {output} ({len(canonical.data)} bytes)")


def _layouts(disk: Disk, captures: Path | None) -> dict[int, LayoutReading] | None:
    if captures is None:
        return None
    try:
        return layouts_for(disk, load_captures(captures))
    except ValueError as error:
        raise fail(str(error)) from error


def provenance(
    image: ImageArgument,
    *,
    captures: Annotated[
        Path | None,
        typer.Option(
            "--captures", help="also judge how each side was written, from what a dump --raw kept"
        ),
    ] = None,
    json_output: JsonOption = False,
) -> None:
    disk, _, _, _ = decode_image(image)
    report = provenance_of(disk, layouts=_layouts(disk, captures))

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


def _boot_side(side: SideBoot) -> dict[str, object]:
    return {
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


def _print_boot(report: BootReport) -> None:
    for side in report.sides:
        typer.echo(f"side {side.side}: {side.message}")
        for entry in side.boot_files:
            typer.echo(
                f"  loads #{entry.position} id {entry.file_id} {entry.name!r} "
                f"{entry.size} bytes at ${entry.address:04X}"
            )


def boot(image: ImageArgument, *, json_output: JsonOption = False) -> None:
    disk, _, _, _ = decode_image(image)
    report = predict_boot(disk)
    if json_output:
        sides = [_boot_side(side) for side in report.sides]
        typer.echo(as_json({"path": str(image), "sides": sides}))
    else:
        _print_boot(report)
    failed = any(side.verdict is BootVerdict.FAILS for side in report.sides[:1])
    raise typer.Exit(code=1 if failed else 0)


def doctor(
    *,
    json_output: JsonOption = False,
) -> None:
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
    app.command(
        rich_help_panel=Family.INSPECT,
        help="Describe an image, side by side, and with --files every file on it.",
    )(info)
    app.command(rich_help_panel=Family.CHECK, help="Check an image and report every finding.")(
        verify
    )
    app.command(
        name="hash",
        rich_help_panel=Family.INSPECT,
        help="Hash an image, every side, and its canonical form, which -o also writes out.",
    )(hash_command)
    app.command(
        rich_help_panel=Family.INSPECT,
        help="Report where each side came from: factory, kiosk rewrite, or unknown.",
    )(provenance)
    app.command(
        rich_help_panel=Family.INSPECT,
        help="Predict what the console does when it boots each side.",
    )(boot)
    app.command(
        rich_help_panel=Family.HARDWARE,
        help="Check the installation: version, Python and hardware support.",
    )(doctor)
