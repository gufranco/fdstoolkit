from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final
from xml.etree.ElementTree import ParseError

from fastapi import HTTPException

from fdstoolkit.core.canon import profile_by_name
from fdstoolkit.core.disk import Disk
from fdstoolkit.identify.dat import identify as identify_image
from fdstoolkit.identify.dat import load_dat
from fdstoolkit.identify.datfile import build_dat
from fdstoolkit.identify.integrity import inspect_disk
from fdstoolkit.master.corpus import build_masters
from fdstoolkit.master.reference import ReferenceSet, reference_from
from fdstoolkit.master.splice import splice
from fdstoolkit.quality.consensus import build_consensus
from fdstoolkit.quality.health import measure_health
from fdstoolkit.ui.schemas import (
    ConsensusSpec,
    CorpusSpec,
    DatBuildSpec,
    FileResult,
    HealthSpec,
    IdentifySpec,
    ImageSpec,
    ReferenceBuildSpec,
    ReferenceVerifySpec,
    ReportedFile,
    RowsResult,
    SpliceSpec,
)
from fdstoolkit.ui.shared import (
    BAD_REQUEST,
    UNPROCESSABLE,
    bytes_of,
    decode_payload,
    encoded,
    named_file,
    refuse,
    rows_of,
)

ACROSS_DISK: Final = "disk"
ACROSS_CORPUS: Final = "corpus"
ACROSS: Final = (ACROSS_DISK, ACROSS_CORPUS)


def _corpus(spec: CorpusSpec) -> list[tuple[str, Disk]]:
    if not spec.images:
        refuse("this needs at least one image", status=UNPROCESSABLE)
    names = spec.names or [f"image{index}.fds" for index in range(len(spec.images))]
    return [
        (name, decode_payload(payload)[0])
        for name, payload in zip(names, spec.images, strict=False)
    ]


def health(spec: HealthSpec) -> RowsResult:
    if not spec.reads:
        refuse("measuring the drive needs at least one read to compare", status=UNPROCESSABLE)
    reference, _, _ = decode_payload(spec.data)
    reads = [decode_payload(entry)[0] for entry in spec.reads]
    profile = measure_health(reference, reads)
    return RowsResult(rows=rows_of([asdict(profile)]))


def integrity(spec: ImageSpec) -> RowsResult:
    disk, _, _ = decode_payload(spec.data)
    report = inspect_disk(disk)
    return RowsResult(rows=rows_of(report.suspicions), ok=not report.suspicions)


def splice_blocks(spec: SpliceSpec) -> FileResult:
    if not spec.donors:
        refuse("splicing needs at least one donor", status=UNPROCESSABLE)
    primary, _, _ = decode_payload(spec.data)
    donors = [decode_payload(entry)[0] for entry in spec.donors]
    result = splice(primary, donors)
    return named_file(spec.name, encoded(result.disk))


def consensus(spec: ConsensusSpec) -> ReportedFile | RowsResult:
    if spec.across not in ACROSS:
        refuse(f"consensus runs across {' or '.join(ACROSS)}, not {spec.across}")
    if spec.across == ACROSS_CORPUS:
        return _masters(spec)
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


def _masters(spec: CorpusSpec) -> RowsResult:
    report = build_masters(_corpus(spec), profile=profile_by_name(spec.profile))
    rows = [
        {
            "game": str(group.key),
            "members": len(group.members),
            "variants": group.variants,
            "digest": group.digest,
        }
        for group in report.groups
    ]
    return RowsResult(
        headline=f"{len(report.unanimous)} of {len(report.groups)} game(s) unanimous",
        rows=rows,
        ok=not report.contested,
    )


def reference_build(spec: ReferenceBuildSpec) -> FileResult:
    report = build_masters(_corpus(spec), profile=profile_by_name(spec.profile))
    published = reference_from(report, version=spec.set_version)
    return named_file("reference.json", published.to_json().encode("utf-8"))


def reference_verify(spec: ReferenceVerifySpec) -> RowsResult:
    disk, _, _ = decode_payload(spec.data)
    try:
        published = ReferenceSet.from_json(bytes_of(spec.reference).decode("utf-8"))
    except (ValueError, KeyError, UnicodeDecodeError) as error:
        message = f"this is not a reference set: {error}"
        raise HTTPException(status_code=BAD_REQUEST, detail=message) from error
    match = published.verify(disk)
    return RowsResult(rows=rows_of([asdict(match)]), ok=str(match.verdict) == "match")


def dat_build(spec: DatBuildSpec) -> FileResult:
    entries = [(name, encoded(disk)) for name, disk in _corpus(spec)]
    body = build_dat(
        entries,
        name=spec.name,
        version=spec.set_version,
        author=spec.author or None,
    )
    return named_file("fdstoolkit.dat", body.encode("utf-8"))


def identify(spec: IdentifySpec) -> RowsResult:
    _, data, _ = decode_payload(spec.data)
    with TemporaryDirectory(prefix="fdstoolkit-ui-") as directory:
        path = Path(directory) / "catalogue.dat"
        path.write_bytes(bytes_of(spec.dat))
        try:
            catalogue = load_dat(path)
        except (ValueError, KeyError, OSError, ParseError) as error:
            message = f"this is not a catalogue: {error}"
            raise HTTPException(status_code=BAD_REQUEST, detail=message) from error
    found = identify_image(data, catalogue)
    return RowsResult(
        rows=[
            {
                "kind": str(found.kind),
                "name": found.entry.name if found.entry else "",
                "matched": found.matched_on,
                "same_size": found.same_size,
            }
        ],
        ok=found.entry is not None,
    )
