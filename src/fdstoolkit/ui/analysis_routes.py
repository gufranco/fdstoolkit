from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree.ElementTree import ParseError

from fastapi import HTTPException

from fdstoolkit.core.canon import profile_by_name
from fdstoolkit.core.disk import Disk
from fdstoolkit.drive.bracket import Setting, bracket_of
from fdstoolkit.flux.analysis import analyse_capture
from fdstoolkit.flux.decode import decode_capture
from fdstoolkit.flux.load import CaptureFormat, detect_format, load_capture
from fdstoolkit.identify.cache import DatCache
from fdstoolkit.identify.dat import identify as identify_image
from fdstoolkit.identify.dat import load_dat
from fdstoolkit.identify.datfile import build_dat
from fdstoolkit.identify.firmware import emulator_notes, identify_bios
from fdstoolkit.identify.integrity import inspect_disk
from fdstoolkit.master.corpus import build_masters
from fdstoolkit.master.reference import ReferenceSet, reference_from
from fdstoolkit.master.splice import splice
from fdstoolkit.quality.calibrate import calibrate
from fdstoolkit.quality.consensus import build_consensus
from fdstoolkit.ui.schemas import (
    BiosSpec,
    CalibrateSpec,
    CorpusSpec,
    DatBuildSpec,
    DecodeSpec,
    FileResult,
    IdentifySpec,
    ImageSpec,
    ImagesSpec,
    ReferenceBuildSpec,
    ReferenceVerifySpec,
    RowsResult,
    SpliceSpec,
    SweepSpec,
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


def _corpus(spec: CorpusSpec) -> list[tuple[str, Disk]]:
    if not spec.images:
        refuse("this needs at least one image", status=UNPROCESSABLE)
    names = spec.names or [f"image{index}.fds" for index in range(len(spec.images))]
    return [
        (name, decode_payload(payload)[0])
        for name, payload in zip(names, spec.images, strict=False)
    ]


def _capture(payload: str, fmt: str | None):  # noqa: ANN202
    data = bytes_of(payload)
    try:
        chosen = CaptureFormat(fmt) if fmt else detect_format(data)
        return load_capture(data, fmt=chosen)
    except (ValueError, IndexError, KeyError) as error:
        message = f"this capture could not be read: {error}"
        raise HTTPException(status_code=BAD_REQUEST, detail=message) from error


def calibrate_drive(spec: CalibrateSpec) -> RowsResult:
    if not spec.reads:
        refuse("calibrating needs at least one read to compare", status=UNPROCESSABLE)
    reference, _, _ = decode_payload(spec.data)
    reads = [decode_payload(entry)[0] for entry in spec.reads]
    profile = calibrate(reference, reads, flux_margin=spec.margin)
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


def consensus(spec: ImagesSpec) -> FileResult:
    if not spec.images:
        refuse("a consensus needs at least one dump", status=UNPROCESSABLE)
    disks = [decode_payload(entry)[0] for entry in spec.images]
    return named_file("consensus.fds", encoded(build_consensus(disks).disk))


def masters(spec: CorpusSpec) -> RowsResult:
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
    return RowsResult(rows=rows, ok=all(group.variants <= 1 for group in report.groups))


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


def bios(spec: BiosSpec) -> RowsResult:
    data = bytes_of(spec.data)
    report = identify_bios(data)
    notes = emulator_notes(report.revision, exact_size=report.exact_size)
    rows = [{"revision": str(report.revision), "exact_size": report.exact_size}]
    rows.extend({"emulator": name, "note": note} for name, note in sorted(notes.items()))
    return RowsResult(rows=rows)


def dat_cache() -> RowsResult:
    cache = DatCache()
    return RowsResult(rows=[{"path": str(cache.root), "catalogues": len(list(cache.entries()))}])


def flux_decode(spec: DecodeSpec) -> FileResult:
    capture = _capture(spec.data, spec.fmt)
    try:
        disk, _ = decode_capture(capture, adaptive=not spec.fixed)
    except (ValueError, IndexError) as error:
        message = f"this capture could not be decoded: {error}"
        raise HTTPException(status_code=BAD_REQUEST, detail=message) from error
    return named_file("decoded.fds", encoded(disk))


def tune_sweep(spec: SweepSpec) -> RowsResult:
    if not spec.captures:
        refuse("a sweep needs at least one capture", status=UNPROCESSABLE)
    settings: list[Setting] = []
    for index, payload in enumerate(spec.captures):
        capture = _capture(payload, spec.fmt)
        report = analyse_capture(capture)
        track = report.tracks[0]
        settings.append(
            Setting(
                label=f"capture {index + 1}",
                bit_rate_hz=track.revolutions[0].bit_rate_hz,
                margin=track.worst_margin,
                errors=0,
            )
        )
    bracket = bracket_of(settings)
    return RowsResult(
        rows=[
            {
                "centre_hz": bracket.centre,
                "width": bracket.width,
                "health": bracket.health,
                "best": bracket.best.label if bracket.best else "",
            }
        ]
    )
