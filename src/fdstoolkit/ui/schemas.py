from __future__ import annotations

from typing import Annotated, Any, Final, Self

from pydantic import BaseModel, Field, Strict

from fdstoolkit.core.diagnostics import Diagnostic
from fdstoolkit.core.disk import SIDES_PER_DISK, Disk
from fdstoolkit.core.diskinfo import PROFILES
from fdstoolkit.drive.monitor import DEFAULT_READS, MAX_READS, Calibration
from fdstoolkit.hardware.session import MAX_PASSES, MAX_RETRIES
from fdstoolkit.identify.hashes import Digests
from fdstoolkit.quality.grade import GradedReport
from fdstoolkit.quality.reads import ReadStatistics

MAX_ADDRESS: Final = 0xFFFF
MAX_NAME: Final = 120
GAME_NAME_LENGTH: Final = 3
FILE_NAME_LENGTH: Final = 8

SideCount = Annotated[int, Strict(), Field(ge=1, le=SIDES_PER_DISK)]


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
    side: int | None = Field(None, ge=0)
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


class FileResult(BaseModel):
    name: str
    data: str
    size: int


class HashResult(BaseModel):
    whole: DigestView
    sides: list[DigestView]
    canonical: str
    retroachievements: str
    file: FileResult | None = None


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


class WeakView(BaseModel):
    side: int
    block: int
    kind: str
    unstable: int
    invalid: int
    reads: int
    missing: int


class WeakResult(BaseModel):
    reads: int
    weak: list[WeakView]


class ReadsResult(BaseModel):
    passes: int
    stability: float
    decay: str
    bits_lost: int
    bits_gained: int
    unstable_blocks: list[list[int]]
    missing_blocks: list[list[int]]

    @classmethod
    def of(cls, stats: ReadStatistics) -> Self:
        return cls(
            passes=stats.passes,
            stability=stats.stability,
            decay=str(stats.decay),
            bits_lost=stats.ones_lost,
            bits_gained=stats.ones_gained,
            unstable_blocks=[list(pair) for pair in stats.unstable_blocks],
            missing_blocks=[list(item) for item in stats.missing],
        )


class CalibrationResult(BaseModel):
    headline: str
    mode: str
    rows: list[dict[str, Any]]
    ok: bool

    @classmethod
    def of(cls, result: Calibration) -> Self:
        return cls(
            headline=result.headline,
            mode=str(result.mode),
            rows=result.rows(),
            ok=result.clean,
        )


class ImageSpec(BaseModel):
    data: str = Field(description="the image, base64 encoded")
    name: str = "disk.fds"


class HashSpec(ImageSpec):
    profile: str = "content"
    canonical_image: bool = False


class VerifySpec(ImageSpec):
    strict: bool = False


class GradeSpec(ImageSpec):
    reads: list[str] = Field(default_factory=list)
    captures: str | None = Field(None, description="the capture bundle a dump kept, as a zip")


class ReadsSpec(BaseModel):
    images: list[str] = Field(default_factory=list)
    captures: str | None = Field(None, description="the capture bundle a dump kept, as a zip")


class CalibrateSpec(BaseModel):
    mode: str = "speed"
    reference: str | None = Field(
        None, description="an image of the disk in the drive, dumped by a drive you trust"
    )
    side: int = Field(0, ge=0, le=SIDES_PER_DISK - 1)
    passes: int = Field(DEFAULT_READS, ge=1, le=MAX_READS)
    bracket: bool = False
    captures: str | None = Field(None, description="the capture bundle a dump kept, as a zip")


class BlankSpec(BaseModel):
    sides: SideCount = 1
    formatted: bool = False
    headered: bool = False
    game_name: str = Field("   ", min_length=GAME_NAME_LENGTH, max_length=GAME_NAME_LENGTH)
    calibration: bool = False


class ConvertSpec(ImageSpec):
    to_qd: bool = False
    headered: bool = False


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


def _no_rows() -> list[dict[str, Any]]:
    return []


def _no_files() -> list[FileResult]:
    return []


class Catalogue(BaseModel):
    version: str
    forms: list[dict[str, Any]] = Field(default_factory=_no_rows)
    families: list[str] = Field(default_factory=list)
    profiles: list[ProfileView]
    export_targets: list[str]
    commands: list[str]
    extras: dict[str, Any] = Field(default_factory=dict)


class ImagesSpec(BaseModel):
    images: list[str] = Field(default_factory=list)


class StrictSpec(ImageSpec):
    strict: bool = False


class DiffSpec(BaseModel):
    left: str
    right: str
    explain: bool = True


class SideSpec(ImageSpec):
    side: int = 0


class InsertSpec(ImageSpec):
    file: str
    file_name: str = Field(..., min_length=1, max_length=FILE_NAME_LENGTH)
    address: int = Field(0x6000, ge=0, le=MAX_ADDRESS)
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


class SaveSpec(BaseModel):
    action: str = "find"
    images: list[str] = Field(default_factory=list)
    save: str | None = None
    played: str | None = None
    recipes: str | None = None
    save_as: str = "ips"
    name: str = "disk.fds"


class SpliceSpec(ImageSpec):
    donors: list[str] = Field(default_factory=list)


class ExportSpec(ImageSpec):
    target: str


class BuildSpec(BaseModel):
    manifest: str


class ConsensusSpec(BaseModel):
    images: list[str] = Field(default_factory=list)
    captures: str | None = Field(None, description="the capture bundle a dump kept, as a zip")


class DumpSpec(BaseModel):
    sides: SideCount = 1
    passes: int = Field(1, ge=1, le=MAX_PASSES)
    retries: int = Field(3, ge=0, le=MAX_RETRIES)
    keep_captures: bool = False


class WriteSpec(BaseModel):
    data: str | None = None
    calibration: bool = False
    trusted_drive: bool = False
    retries: int = Field(3, ge=0, le=MAX_RETRIES)
    long_side: bool = False
    confirm: bool = False


class SurfaceSpec(BaseModel):
    sides: SideCount = 1
    passes: int = Field(1, ge=1, le=MAX_PASSES)
    quick: bool = False
    finish: str = "leave"
    confirm: bool = False


class TextResult(BaseModel):
    text: str
    ok: bool = True


class RowsResult(BaseModel):
    headline: str = ""
    rows: list[dict[str, Any]] = Field(default_factory=_no_rows)
    ok: bool = True


class DiffResult(BaseModel):
    headline: str
    identical: bool
    same_software: bool | None = None
    blocks: list[dict[str, Any]] = Field(default_factory=_no_rows)
    differences: list[dict[str, Any]] = Field(default_factory=_no_rows)
    file_changes: list[dict[str, Any]] = Field(default_factory=_no_rows)
    ok: bool = True


class ReportedFile(BaseModel):
    headline: str
    file: FileResult
    rows: list[dict[str, Any]] = Field(default_factory=_no_rows)
    ok: bool = True


class JobView(BaseModel):
    id: str
    command: str
    writes: bool
    stoppable: bool = False
    stopping: bool = False
    state: str
    steps: list[str] = Field(default_factory=list)
    prompt: str = ""
    result: dict[str, Any] | None = None
    error: str = ""


class CurrentJob(BaseModel):
    job: JobView | None = None


class AnswerSpec(BaseModel):
    yes: bool


class FilesResult(BaseModel):
    files: list[FileResult] = Field(default_factory=_no_files)


class DumpedResult(FileResult):
    grade: str
    captures: FileResult | None = None
