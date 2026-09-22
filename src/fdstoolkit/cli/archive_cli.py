from __future__ import annotations

import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated

import typer

from fdstoolkit.archive.store import Archive, DumpRecord, disk_identity
from fdstoolkit.archive.trend import trend_of
from fdstoolkit.cli.common import decode_image, fail
from fdstoolkit.core.canon import canonicalise, digest_string
from fdstoolkit.core.diskinfo import RELEASE_PROFILE
from fdstoolkit.quality.confidence import score_disk
from fdstoolkit.quality.grade import grade_disk
from fdstoolkit.report import as_json


def default_db() -> Path:
    root = os.environ.get("XDG_DATA_HOME")
    base = Path(root) if root else Path.home() / ".local" / "share"
    return base / "fdstoolkit" / "archive.db"


def archive_add(
    image: Annotated[Path, typer.Argument(help="a dump of a physical disk")],
    db: Annotated[Path | None, typer.Option("--db", help="where the archive lives")] = None,
    taken: Annotated[
        str | None, typer.Option("--taken", help="the day of the dump, YYYY-MM-DD")
    ] = None,
    drive: Annotated[str, typer.Option("--drive", help="the drive that read it")] = "",
    notes: Annotated[str, typer.Option("--notes", help="anything worth remembering")] = "",
    bad_blocks: Annotated[
        int | None, typer.Option("--bad-blocks", help="override the counted bad blocks")
    ] = None,
) -> None:
    """Record a dump so this disk can be watched over the years."""
    when = taken or datetime.now(tz=UTC).date().isoformat()
    try:
        date.fromisoformat(when)
    except ValueError as error:
        message = f"{when} is not a date in YYYY-MM-DD form"
        raise fail(message) from error

    disk, findings, _, _ = decode_image(image)
    confidence = score_disk(disk)
    report = grade_disk(confidence=confidence, findings=findings)
    total = len(confidence.blocks)
    bad = bad_blocks if bad_blocks is not None else len(confidence.low_confidence_blocks)
    identity = disk_identity(disk)

    with Archive(db or default_db()) as archive:
        archive.record(
            DumpRecord(
                disk_id=identity,
                taken=when,
                digest=digest_string(canonicalise(disk, RELEASE_PROFILE)),
                grade=report.grade.value,
                confidence=report.confidence,
                blocks_total=total,
                blocks_bad=bad,
                drive=drive,
                notes=notes,
            )
        )

    typer.echo(f"recorded {when}, {report.grade.value}, {bad} of {total} bad, as {identity}")


def archive_trend(
    db: Annotated[Path | None, typer.Option("--db", help="where the archive lives")] = None,
    disk: Annotated[str | None, typer.Option("--disk", help="one disk identity")] = None,
    *,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Report how a disk has changed across the dumps on record."""
    with Archive(db or default_db()) as archive:
        wanted = [disk] if disk else list(archive.disks())
        if disk and not archive.history(disk):
            message = f"no history for {disk}"
            raise fail(message)
        trends = [trend_of(archive.history(item)) for item in wanted if archive.history(item)]

    if json_output:
        typer.echo(
            as_json(
                [
                    {
                        "disk_id": item.disk_id,
                        "direction": item.direction.value,
                        "blocks_per_year": round(item.blocks_per_year, 4),
                        "years": round(item.years, 4),
                        "points": len(item.points),
                        "years_remaining": (
                            None if item.years_remaining is None else round(item.years_remaining, 2)
                        ),
                    }
                    for item in trends
                ]
            )
        )
        raise typer.Exit(code=0)

    if not trends:
        typer.echo("no disk on record")
        raise typer.Exit(code=0)
    for item in trends:
        typer.echo(item.render())
    raise typer.Exit(code=0)


def register(app: typer.Typer) -> None:
    app.command(name="archive-add")(archive_add)
    app.command(name="archive-trend")(archive_trend)
