from __future__ import annotations

from fdstoolkit.master.splice import splice
from fdstoolkit.quality.consensus import build_consensus
from fdstoolkit.ui.schemas import ConsensusSpec, FileResult, ReportedFile, SpliceSpec
from fdstoolkit.ui.shared import UNPROCESSABLE, decode_payload, encoded, named_file, refuse


def splice_blocks(spec: SpliceSpec) -> FileResult:
    if not spec.donors:
        refuse("splicing needs at least one donor", status=UNPROCESSABLE)
    primary, _, _ = decode_payload(spec.data)
    donors = [decode_payload(entry)[0] for entry in spec.donors]
    result = splice(primary, donors)
    return named_file(spec.name, encoded(result.disk))


def consensus(spec: ConsensusSpec) -> ReportedFile:
    if not spec.images:
        refuse("a consensus needs at least one dump", status=UNPROCESSABLE)
    result = build_consensus([decode_payload(entry)[0] for entry in spec.images])
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
