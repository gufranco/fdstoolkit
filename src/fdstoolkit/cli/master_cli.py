from __future__ import annotations

from pathlib import Path
from typing import Annotated, Final

import typer

from fdstoolkit.cli.common import decode_image, fail, guard_output
from fdstoolkit.codecs import fds
from fdstoolkit.core.canon import profile_by_name
from fdstoolkit.core.disk import Disk
from fdstoolkit.identify.datfile import build_dat
from fdstoolkit.master.corpus import build_masters
from fdstoolkit.master.reference import ReferenceSet, Verdict, reference_from
from fdstoolkit.master.splice import splice
from fdstoolkit.report import as_json

SUFFIXES: Final = (".fds", ".qd")


def _collect(root: Path) -> list[tuple[str, Disk]]:
    if not root.is_dir():
        message = f"directory not found: {root}"
        raise fail(message)
    entries = [
        (path.name, decode_image(path)[0])
        for path in sorted(root.rglob("*"))
        if path.suffix.lower() in SUFFIXES
    ]
    if not entries:
        message = f"no image found under {root}"
        raise fail(message)
    return entries


def splice_command(
    image: Annotated[Path, typer.Argument(help="the image to repair")],
    donor: Annotated[
        list[Path], typer.Option("--donor", help="another dump of the same disk, repeatable")
    ],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the result")],
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Repair a bad block by taking it from another dump of the same disk."""
    guard_output(output, force=force)
    primary, _, _, _ = decode_image(image)
    donors = [decode_image(path)[0] for path in donor]

    try:
        result = splice(primary, donors)
    except ValueError as error:
        raise fail(str(error)) from error

    data, _ = fds.encode(result.disk, headered=False)
    output.write_bytes(data)

    for item in result.splices:
        typer.echo(
            f"side {item.side} block {item.block:3d}  {item.kind:<11} "
            f"taken from {donor[item.donor].name}"
        )
    for side_index, block_index in result.unrepaired:
        typer.echo(f"side {side_index} block {block_index}: no donor carries a good copy")
    typer.echo(f"wrote {output} ({len(data)} bytes)")
    raise typer.Exit(code=0 if result.complete else 1)


def masters(
    corpus: Annotated[Path, typer.Argument(help="a directory of dumps")],
    profile: Annotated[
        str, typer.Option("--profile", help="the identity profile to agree on")
    ] = "release",
    *,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Build one master per game by agreement across every dump in a corpus."""
    try:
        chosen = profile_by_name(profile)
    except ValueError as error:
        raise fail(str(error)) from error

    report = build_masters(_collect(corpus), profile=chosen)

    if json_output:
        typer.echo(
            as_json(
                {
                    "profile": chosen.name,
                    "dumps": report.dumps,
                    "groups": len(report.groups),
                    "agreement": round(report.agreement, 6),
                    "contested": [
                        {
                            "game": group.key.label,
                            "digest": group.digest,
                            "variants": group.variants,
                            "agreement": round(group.agreement, 6),
                            "dissenters": list(group.dissenters),
                        }
                        for group in report.contested
                    ],
                }
            )
        )
        raise typer.Exit(code=0 if not report.contested else 1)

    typer.echo(f"profile       {chosen.name}")
    typer.echo(f"dumps         {report.dumps}")
    typer.echo(f"games         {len(report.groups)}")
    typer.echo(f"unanimous     {len(report.unanimous)} of {len(report.groups)}")
    for group in report.contested:
        typer.echo(
            f"{group.key.label}: {group.variants} variants, "
            f"{group.agreement:.0%} agree, dissenting {', '.join(group.dissenters)}"
        )
    raise typer.Exit(code=0 if not report.contested else 1)


def reference_build(
    corpus: Annotated[Path, typer.Argument(help="a directory of dumps")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the set")],
    set_version: Annotated[str, typer.Option("--set-version", help="a version for the set")],
    profile: Annotated[str, typer.Option("--profile", help="the identity profile")] = "release",
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Publish a reference digest set others can verify a dump against."""
    guard_output(output, force=force)
    try:
        chosen = profile_by_name(profile)
    except ValueError as error:
        raise fail(str(error)) from error

    reference = reference_from(build_masters(_collect(corpus), profile=chosen), version=set_version)
    output.write_text(reference.to_json(), encoding="utf-8")
    typer.echo(f"wrote {output} ({len(reference.entries)} entries)")


def reference_verify(
    image: Annotated[Path, typer.Argument(help="the image to check")],
    reference: Annotated[Path, typer.Option("--set", help="a reference set")],
    *,
    json_output: Annotated[bool, typer.Option("--json", help="print JSON")] = False,
) -> None:
    """Check an image against a published reference set."""
    if not reference.is_file():
        message = f"file not found: {reference}"
        raise fail(message)
    try:
        loaded = ReferenceSet.from_json(reference.read_text(encoding="utf-8"))
    except ValueError as error:
        raise fail(str(error)) from error

    disk, _, _, _ = decode_image(image)
    match = loaded.verify(disk)

    if json_output:
        typer.echo(
            as_json(
                {
                    "verdict": match.verdict.value,
                    "digest": match.digest,
                    "expected": match.entry.digest if match.entry else None,
                    "game": match.entry.key.label if match.entry else None,
                }
            )
        )
        raise typer.Exit(code=0 if match.matched else 1)

    typer.echo(f"digest        {match.digest}")
    typer.echo(f"verdict       {match.verdict.value}")
    if match.entry is not None:
        typer.echo(f"game          {match.entry.key.label}")
        typer.echo(f"dumps         {match.entry.dumps}")
        if match.verdict is Verdict.MISMATCH:
            typer.echo(f"expected      {match.entry.digest}")
    raise typer.Exit(code=0 if match.matched else 1)


def dat_build(
    corpus: Annotated[Path, typer.Argument(help="a directory of images")],
    output: Annotated[Path, typer.Option("-o", "--output", help="where to write the DAT")],
    name: Annotated[str, typer.Option("--name", help="the set name")],
    set_version: Annotated[str, typer.Option("--set-version", help="a version for the set")],
    author: Annotated[str | None, typer.Option("--author", help="who built it")] = None,
    *,
    force: Annotated[bool, typer.Option("--force", help="overwrite the output")] = False,
) -> None:
    """Emit a DAT so the results reach the tools the community already uses."""
    guard_output(output, force=force)
    if not corpus.is_dir():
        message = f"directory not found: {corpus}"
        raise fail(message)

    entries = [
        (path.name, path.read_bytes())
        for path in sorted(corpus.rglob("*"))
        if path.suffix.lower() in SUFFIXES
    ]

    try:
        text = build_dat(entries, name=name, version=set_version, author=author)
    except ValueError as error:
        raise fail(str(error)) from error

    output.write_text(text, encoding="utf-8")
    typer.echo(f"wrote {output} ({len(entries)} games)")


def register(app: typer.Typer) -> None:
    app.command(name="splice")(splice_command)
    app.command()(masters)
    app.command(name="reference-build")(reference_build)
    app.command(name="reference-verify")(reference_verify)
    app.command(name="dat-build")(dat_build)
