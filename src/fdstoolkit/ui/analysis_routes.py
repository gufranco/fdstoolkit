from __future__ import annotations

from typing import TYPE_CHECKING

from fdstoolkit.drive.recovery import Rebuild, rebuild
from fdstoolkit.master.splice import splice
from fdstoolkit.quality.consensus import build_consensus
from fdstoolkit.ui.schemas import ConsensusSpec, FileResult, ReportedFile, SpliceSpec

if TYPE_CHECKING:
    from fdstoolkit.core.disk import Disk

from fdstoolkit.ui.shared import (
    UNPROCESSABLE,
    bundle_of,
    decode_payload,
    encoded_file,
    refuse,
)


def splice_blocks(spec: SpliceSpec) -> FileResult:
    if not spec.donors:
        refuse("splicing needs at least one donor", status=UNPROCESSABLE)
    primary, _, _ = decode_payload(spec.data)
    donors = [decode_payload(entry)[0] for entry in spec.donors]
    try:
        result = splice(primary, donors)
    except ValueError as error:
        refuse(str(error), status=UNPROCESSABLE)
    return encoded_file(spec.name, result.disk)


def _captured_only(rebuilt: Rebuild) -> ReportedFile:
    unresolved: list[dict[str, object]] = [
        {"side": side, "block": block} for side, block in rebuilt.unresolved
    ]
    return ReportedFile(
        headline="; ".join(line.strip() for line in rebuilt.lines)
        or "every block read clean in the captures",
        file=encoded_file("consensus.fds", rebuilt.disk),
        rows=unresolved,
        ok=not unresolved,
    )


def _merged(disks: list[Disk]) -> ReportedFile:
    try:
        result = build_consensus(disks)
    except ValueError as error:
        refuse(str(error), status=UNPROCESSABLE)
    rows: list[dict[str, object]] = [
        *({"side": side, "block": block, "finding": text} for side, block, text in result.findings),
        *(
            {"side": side, "block": block, "finding": f"missing from {absent} dump(s)"}
            for side, block, absent in result.missing
        ),
    ]
    headline = (
        f"{len(result.disagreements)} block(s) disagree across the dumps"
        if result.disagreements
        else "every dump agrees on every block"
    )
    file = encoded_file("consensus.fds", result.disk)
    return ReportedFile(headline=headline, file=file, rows=rows, ok=not result.disagreements)


def consensus(spec: ConsensusSpec) -> ReportedFile:
    if not spec.images and spec.captures is None:
        refuse("a consensus needs dumps, saved captures, or both", status=UNPROCESSABLE)
    disks = [decode_payload(entry)[0] for entry in spec.images]
    if spec.captures is None:
        return _merged(disks)
    rebuilt = rebuild(bundle_of(spec.captures))
    if not disks:
        return _captured_only(rebuilt)
    return _merged([*disks, rebuilt.disk])
