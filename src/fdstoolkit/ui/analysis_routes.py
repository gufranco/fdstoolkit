from __future__ import annotations

from fdstoolkit.drive.recovery import rebuild
from fdstoolkit.master.splice import splice
from fdstoolkit.quality.consensus import build_consensus
from fdstoolkit.ui.schemas import ConsensusSpec, FileResult, ReportedFile, SpliceSpec
from fdstoolkit.ui.shared import (
    UNPROCESSABLE,
    bundle_of,
    decode_payload,
    encoded,
    named_file,
    refuse,
)


def splice_blocks(spec: SpliceSpec) -> FileResult:
    if not spec.donors:
        refuse("splicing needs at least one donor", status=UNPROCESSABLE)
    primary, _, _ = decode_payload(spec.data)
    donors = [decode_payload(entry)[0] for entry in spec.donors]
    result = splice(primary, donors)
    return named_file(spec.name, encoded(result.disk))


def consensus(spec: ConsensusSpec) -> ReportedFile:
    if not spec.images and spec.captures is None:
        refuse("a consensus needs dumps, saved captures, or both", status=UNPROCESSABLE)
    disks = [decode_payload(entry)[0] for entry in spec.images]
    if spec.captures is not None:
        rebuilt = rebuild(bundle_of(spec.captures))
        if not disks:
            rows = [{"side": side, "block": block} for side, block in rebuilt.unresolved]
            return ReportedFile(
                headline="; ".join(line.strip() for line in rebuilt.lines)
                or "every block read clean in the captures",
                file=named_file("consensus.fds", encoded(rebuilt.disk)),
                rows=rows,
                ok=not rows,
            )
        disks.append(rebuilt.disk)
    try:
        result = build_consensus(disks)
    except ValueError as error:
        refuse(str(error), status=UNPROCESSABLE)
    rows = [{"side": side, "block": block} for side, block in result.disagreements]
    headline = (
        f"{len(rows)} block(s) disagree across the dumps"
        if rows
        else "every dump agrees on every block"
    )
    return ReportedFile(
        headline=headline,
        file=named_file("consensus.fds", encoded(result.disk)),
        rows=rows,
        ok=not rows,
    )
