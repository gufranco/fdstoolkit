from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from fdstoolkit.cli.common import (
    Family,
    ForceOption,
    JsonOption,
    OutputOption,
    container_of,
    decode_image,
    encode_image,
    fail,
    guard_output,
    load_captures,
)
from fdstoolkit.core.disk import Disk
from fdstoolkit.drive.recovery import Rebuild, rebuild
from fdstoolkit.master.splice import SpliceResult, splice
from fdstoolkit.quality.consensus import ConsensusResult, build_consensus
from fdstoolkit.report import as_json

RepairedArgument = Annotated[Path, typer.Argument(help="the image to repair")]
DonorOption = Annotated[
    list[Path], typer.Option("--donor", help="another dump of the same disk, repeatable")
]
MergedOption = Annotated[
    Path, typer.Option("-o", "--output", help="where to write the merged disk")
]
DumpsArgument = Annotated[
    list[Path] | None, typer.Argument(help="dumps of one disk, two or more without captures")
]
CapturesOption = Annotated[
    Path | None,
    typer.Option("--captures", help="the captures a dump --raw kept, a folder or a zip"),
]
MapOption = Annotated[bool, typer.Option("--map", help="print the per-block agreement")]


def _spliced(primary: Disk, donors: list[Disk]) -> SpliceResult:
    try:
        return splice(primary, donors)
    except ValueError as error:
        raise fail(str(error)) from error


def _print_splices(result: SpliceResult, donor: list[Path]) -> None:
    for item in result.splices:
        typer.echo(
            f"side {item.side} block {item.block:3d}  {item.kind:<11} "
            f"taken from {donor[item.donor].name}"
        )
    for side_index, block_index in result.unrepaired:
        typer.echo(f"side {side_index} block {block_index}: no donor carries a good copy")


def splice_command(
    image: RepairedArgument,
    donor: DonorOption,
    output: OutputOption,
    *,
    force: ForceOption = False,
) -> None:
    container = container_of(output)
    guard_output(output, force=force)
    primary, _, _, _ = decode_image(image)
    result = _spliced(primary, [decode_image(path)[0] for path in donor])
    data = encode_image(result.disk, container)
    output.write_bytes(data)
    _print_splices(result, donor)
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    raise typer.Exit(code=0 if result.complete else 1)


def _readable_dumps(dumps: list[Path], captures: Path | None) -> None:
    if not dumps and captures is None:
        message = "a consensus needs dumps, saved captures, or both"
        raise fail(message)
    missing = [path for path in dumps if not path.is_file()]
    if missing:
        message = f"not found: {', '.join(str(path) for path in missing)}"
        raise fail(message)


def consensus(
    output: MergedOption,
    paths: DumpsArgument = None,
    *,
    captures: CapturesOption = None,
    force: ForceOption = False,
    stability_map: MapOption = False,
    json_output: JsonOption = False,
) -> None:
    dumps = paths or []
    _readable_dumps(dumps, captures)
    container_of(output)
    guard_output(output, force=force)
    rebuilt = None if captures is None else rebuild(load_captures(captures))
    disks = [decode_image(path)[0] for path in dumps]
    if rebuilt is not None and not disks:
        _write_rebuilt(rebuilt, output, json_output=json_output)
    if rebuilt is not None:
        for line in rebuilt.lines:
            typer.echo(line, err=json_output)
    merged = [*disks, *(() if rebuilt is None else (rebuilt.disk,))]
    _disk_consensus(merged, output, stability_map=stability_map, json_output=json_output)


def _write_rebuilt(rebuilt: Rebuild, output: Path, *, json_output: bool) -> NoReturn:
    data = encode_image(rebuilt.disk, container_of(output))
    output.write_bytes(data)
    code = 0 if not rebuilt.unresolved else 1
    if json_output:
        unresolved = [list(item) for item in rebuilt.unresolved]
        typer.echo(as_json({"output": str(output), "bytes": len(data), "unresolved": unresolved}))
        raise typer.Exit(code=code)
    for line in rebuilt.lines:
        typer.echo(line)
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    raise typer.Exit(code=code)


def _consensus_built(disks: list[Disk]) -> ConsensusResult:
    try:
        return build_consensus(disks)
    except ValueError as error:
        raise fail(str(error)) from error


def _print_consensus(result: ConsensusResult, *, stability_map: bool) -> None:
    for entry in result.stability if stability_map else ():
        typer.echo(
            f"side {entry.side} block {entry.block:3d}  {entry.kind:<11} "
            f"{entry.agreement:6.1%}  {entry.variants} variant(s)  {entry.verdict}"
        )
    for side_index, block_index, finding in result.findings:
        typer.echo(f"side {side_index} block {block_index}: {finding}")
    for side_index, block_index, absent in result.missing:
        typer.echo(
            f"side {side_index} block {block_index}: missing from {absent} dump(s), "
            "decided by the others"
        )


def _disk_consensus(
    disks: list[Disk], output: Path, *, stability_map: bool, json_output: bool
) -> NoReturn:
    result = _consensus_built(disks)
    data = encode_image(result.disk, container_of(output))
    output.write_bytes(data)
    code = 0 if not result.disagreements else 1
    if json_output:
        payload = {
            "output": str(output),
            "bytes": len(data),
            "disagreements": [list(item) for item in result.disagreements],
            "missing": [list(item) for item in result.missing],
        }
        typer.echo(as_json(payload))
        raise typer.Exit(code=code)
    _print_consensus(result, stability_map=stability_map)
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    raise typer.Exit(code=code)


def register(app: typer.Typer) -> None:
    app.command(
        name="splice",
        rich_help_panel=Family.REPAIR,
        help="Repair a bad block by taking it from another dump of the same disk.",
    )(splice_command)
    app.command(
        rich_help_panel=Family.REPAIR,
        help="Merge dumps of one disk block by block, by majority, and name every disagreement.",
    )(consensus)
