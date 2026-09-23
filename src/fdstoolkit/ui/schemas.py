from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, Field

from fdstoolkit.core.diagnostics import Diagnostic
from fdstoolkit.core.disk import Disk
from fdstoolkit.core.diskinfo import PROFILES
from fdstoolkit.drive.advise import Advice
from fdstoolkit.drive.classes import ClassReport
from fdstoolkit.drive.speed import SpeedReport
from fdstoolkit.flux.analysis import CaptureReport
from fdstoolkit.identify.hashes import Digests
from fdstoolkit.quality.grade import GradedReport
from fdstoolkit.quality.reads import ReadStatistics


class ProfileView(BaseModel):
    name: str
    masks: list[str]

    @classmethod
    def of(cls, name: str) -> Self:
        return cls(name=name, masks=sorted(PROFILES[name].masked))


class DiagnosticView(BaseModel):
    code: str
    severity: str
    message: str
    side: int | None = None
    offset: int | None = None

    @classmethod
    def of(cls, finding: Diagnostic) -> Self:
        return cls(
            code=finding.code,
            severity=str(finding.severity),
            message=finding.message,
            side=finding.side,
            offset=finding.offset,
        )


class FileView(BaseModel):
    side: int
    number: int
    identifier: int
    name: str
    address: int
    kind: str
    size: int
    hidden: bool


class SideView(BaseModel):
    index: int
    blocks: int
    declared_files: int | None
    actual_files: int
    content_size: int


class DiskView(BaseModel):
    sides: list[SideView]
    files: list[FileView]

    @classmethod
    def of(cls, disk: Disk) -> Self:
        sides: list[SideView] = []
        files: list[FileView] = []
        for index, side in enumerate(disk.sides):
            declared = side.declared_file_count
            headers = side.file_headers
            sides.append(
                SideView(
                    index=index,
                    blocks=len(side.blocks),
                    declared_files=declared,
                    actual_files=len(headers),
                    content_size=side.content_size,
                )
            )
            files.extend(
                FileView(
                    side=index,
                    number=header.number,
                    identifier=header.file_id,
                    name=header.name,
                    address=header.address,
                    kind=str(header.kind),
                    size=header.size,
                    hidden=declared is not None and position >= declared,
                )
                for position, header in enumerate(headers)
            )
        return cls(sides=sides, files=files)


class DigestView(BaseModel):
    size: int
    crc32: str
    md5: str
    sha1: str
    sha256: str

    @classmethod
    def of(cls, digests: Digests) -> Self:
        return cls(
            size=digests.size,
            crc32=digests.crc32,
            md5=digests.md5,
            sha1=digests.sha1,
            sha256=digests.sha256,
        )


class HashResult(BaseModel):
    whole: DigestView
    sides: list[DigestView]
    canonical: str
    retroachievements: str


class VerifyResult(BaseModel):
    ok: bool
    worst_severity: str
    diagnostics: list[DiagnosticView]


class ReasonView(BaseModel):
    passed: bool
    metric: str
    value: float
    threshold: float


class GradeResult(BaseModel):
    grade: str
    confidence: float
    reasons: list[ReasonView]

    @classmethod
    def of(cls, report: GradedReport) -> Self:
        return cls(
            grade=str(report.grade),
            confidence=report.confidence,
            reasons=[
                ReasonView(
                    passed=reason.passed,
                    metric=reason.metric,
                    value=reason.value,
                    threshold=reason.threshold,
                )
                for reason in report.reasons
            ],
        )


class ReadsResult(BaseModel):
    passes: int
    stability: float
    decay: str
    bits_lost: int
    bits_gained: int
    unstable_blocks: list[list[int]]

    @classmethod
    def of(cls, stats: ReadStatistics) -> Self:
        return cls(
            passes=stats.passes,
            stability=stats.stability,
            decay=str(stats.decay),
            bits_lost=stats.ones_lost,
            bits_gained=stats.ones_gained,
            unstable_blocks=[list(pair) for pair in stats.unstable_blocks],
        )


class ClusterView(BaseModel):
    label: int
    centre_ns: float
    spread_ns: float
    count: int


class TrackView(BaseModel):
    index: int
    pulses: int
    bit_cell_ns: float
    bit_rate_hz: float
    clusters: list[ClusterView]
    worst_margin: float
    coherent: bool
    healthy: bool


class FluxResult(BaseModel):
    fmt: str
    tracks: list[TrackView]
    worst_margin: float
    formatted_tracks: int
    blank_tracks: int
    healthy: bool

    @classmethod
    def of(cls, report: CaptureReport, fmt: str) -> Self:
        return cls(
            fmt=fmt,
            tracks=[
                TrackView(
                    index=track.index,
                    pulses=sum(spin.pulses for spin in track.revolutions),
                    bit_cell_ns=track.revolutions[0].base_ns,
                    bit_rate_hz=track.revolutions[0].bit_rate_hz,
                    clusters=[
                        ClusterView(
                            label=cluster.label,
                            centre_ns=cluster.centre_ns,
                            spread_ns=cluster.spread_ns,
                            count=cluster.count,
                        )
                        for cluster in track.revolutions[0].clusters
                    ],
                    worst_margin=track.worst_margin,
                    coherent=track.coherent,
                    healthy=track.healthy,
                )
                for track in report.tracks
            ],
            worst_margin=report.worst_margin,
            formatted_tracks=len(report.formatted),
            blank_tracks=len(report.blank),
            healthy=report.healthy,
        )


class SpeedView(BaseModel):
    bit_rate_hz: float
    cell_ns: float
    counts: float
    cycles_per_byte: float
    error: float
    headroom: float
    verdict: str
    direction: str

    @classmethod
    def of(cls, report: SpeedReport) -> Self:
        return cls(
            bit_rate_hz=report.bit_rate_hz,
            cell_ns=report.cell_ns,
            counts=report.counts,
            cycles_per_byte=report.cycles_per_byte,
            error=report.error,
            headroom=report.headroom,
            verdict=str(report.verdict),
            direction=str(report.direction),
        )


class ActionView(BaseModel):
    stage: str
    subject: str
    finding: str
    action: str
    gain: float


class TuneResult(BaseModel):
    speed: SpeedView
    motion: str
    wow_and_flutter: float
    drift: float
    spread: float
    score: float
    settled: bool
    actions: list[ActionView]

    @classmethod
    def of(cls, advice: Advice) -> Self:
        return cls(
            speed=SpeedView.of(advice.speed),
            motion=str(advice.stability.motion),
            wow_and_flutter=advice.stability.wow_flutter,
            drift=advice.stability.drift,
            spread=advice.stability.spread,
            score=advice.score,
            settled=advice.settled,
            actions=[
                ActionView(
                    stage=str(action.stage),
                    subject=action.subject,
                    finding=action.finding,
                    action=action.action,
                    gain=action.gain,
                )
                for action in advice.actions
            ],
        )


class ClassesResult(BaseModel):
    counts: list[int]
    shares: list[float]
    glitches: int
    glitch_rate: float
    drift: float
    reading: str
    judgeable: bool

    @classmethod
    def of(cls, report: ClassReport) -> Self:
        return cls(
            counts=list(report.counts),
            shares=list(report.shares),
            glitches=report.glitches,
            glitch_rate=report.glitch_rate,
            drift=report.drift,
            reading=str(report.reading),
            judgeable=report.judgeable,
        )


class ImageSpec(BaseModel):
    data: str = Field(description="the image, base64 encoded")
    name: str = "disk.fds"


class HashSpec(ImageSpec):
    profile: str = "content"


class VerifySpec(ImageSpec):
    strict: bool = False


class GradeSpec(ImageSpec):
    reads: list[str] = Field(default_factory=list)
    margin: float | None = None


class ReadsSpec(BaseModel):
    images: list[str] = Field(default_factory=list)


class CaptureSpec(BaseModel):
    data: str = Field(description="the capture, base64 encoded")
    fmt: str | None = None


class CyclesSpec(BaseModel):
    cycles: float


class BlankSpec(BaseModel):
    sides: int = 1
    formatted: bool = False
    headered: bool = False
    game_name: str = "   "


class ConvertSpec(ImageSpec):
    to_qd: bool = False
    headered: bool = False


class CanonSpec(ImageSpec):
    profile: str = "content"


class DoctorCheck(BaseModel):
    name: str
    status: str
    detail: str


class DoctorResult(BaseModel):
    checks: list[DoctorCheck]
    healthy: bool


class HardwareResult(BaseModel):
    connected: bool
    detail: str


class FileResult(BaseModel):
    name: str
    data: str
    size: int


def _no_rows() -> list[dict[str, Any]]:
    return []


def _no_files() -> list[FileResult]:
    return []


class Catalogue(BaseModel):
    version: str
    forms: list[dict[str, Any]] = Field(default_factory=_no_rows)
    profiles: list[ProfileView]
    capture_formats: list[str]
    export_targets: list[str]
    commands: list[str]
    extras: dict[str, Any] = Field(default_factory=dict)


class ImagesSpec(BaseModel):
    images: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)


class StrictSpec(ImageSpec):
    strict: bool = False


class DiffSpec(BaseModel):
    left: str
    right: str
    explain: bool = False


class SideSpec(ImageSpec):
    side: int = 0


class InsertSpec(ImageSpec):
    file: str
    file_name: str
    address: int = 0x6000
    kind: str = "program"
    side: int = 0


class EditSpec(ImageSpec):
    edits: list[str] = Field(default_factory=list)
    side: int = 0


class RebuildSpec(ImageSpec):
    keep_tail: bool = False
    reveal_hidden: bool = False
    drop_hidden: bool = False
    renumber: bool = False


class PatchSpec(ImageSpec):
    patch: str


class SaveSpec(ImageSpec):
    save: str


class SaveExtractSpec(ImageSpec):
    played: str
    fmt: str = "ips"


class RecipeSpec(ImageSpec):
    recipes: str


class SpliceSpec(ImageSpec):
    donors: list[str] = Field(default_factory=list)


class ConsensusSpec(ImagesSpec):
    pass


class CalibrateSpec(ImageSpec):
    reads: list[str] = Field(default_factory=list)
    margin: float | None = None


class IdentifySpec(ImageSpec):
    dat: str


class BiosSpec(BaseModel):
    data: str
    extract: bool = False


class SplitSpec(ImageSpec):
    stem: str = "fc1234"


class MergeSpec(ImagesSpec):
    headered: bool = False


class ExportSpec(ImageSpec):
    target: str
    bios: str | None = None


class CardSpec(BaseModel):
    sides: int = 1
    firmware: str = "released"


class BuildSpec(BaseModel):
    manifest: str


class CorpusSpec(BaseModel):
    images: list[str] = Field(default_factory=list)
    names: list[str] = Field(default_factory=list)
    profile: str = "release"


class ReferenceBuildSpec(CorpusSpec):
    set_version: str


class ReferenceVerifySpec(ImageSpec):
    reference: str


class DatBuildSpec(CorpusSpec):
    name: str = "Famicom Disk System"
    set_version: str = ""
    author: str = ""


class ArchiveAddSpec(ImageSpec):
    taken: str | None = None
    drive: str = ""
    notes: str = ""
    bad_blocks: int = 0


class ArchiveTrendSpec(BaseModel):
    disk: str | None = None


class SweepSpec(BaseModel):
    captures: list[str] = Field(default_factory=list)
    fmt: str | None = None


class DecodeSpec(CaptureSpec):
    fixed: bool = False


class DumpSpec(BaseModel):
    source: str
    sides: int = 1
    passes: int = 1
    retries: int = 3
    confirm: bool = False


class WriteSpec(BaseModel):
    data: str
    source: str
    retries: int = 3
    confirm: bool = False
    assume_writable: bool = False


class SurfaceSpec(BaseModel):
    source: str
    sides: int = 1
    passes: int = 1
    quick: bool = False
    finish: str = "leave"
    confirm: bool = False
    assume_writable: bool = False


class SubmitSpec(ImageSpec):
    log: str
    dumper: str
    affiliation: str = ""
    photos: list[str] = Field(default_factory=list)


class TextResult(BaseModel):
    text: str
    ok: bool = True


class RowsResult(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=_no_rows)
    ok: bool = True


class FilesResult(BaseModel):
    files: list[FileResult] = Field(default_factory=_no_files)


class DumpedResult(FileResult):
    grade: str
    log: str
