from __future__ import annotations

from fdstoolkit.codecs.fds import decode as _decode_fds
from fdstoolkit.codecs.fds import encode as _encode_fds
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.canon import canonicalise, digest_string, profile_by_name
from fdstoolkit.core.diagnostics import Diagnostic, Severity
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.drive.advise import Advice, advise
from fdstoolkit.drive.classes import ClassReport, measure_classes
from fdstoolkit.drive.speed import SpeedReport, Verdict, from_cycles, measure_speed
from fdstoolkit.drive.stability import measure_stability
from fdstoolkit.flux.analysis import CaptureReport, analyse_capture
from fdstoolkit.flux.load import CaptureFormat, detect_format, load_capture
from fdstoolkit.flux.model import FluxCapture
from fdstoolkit.identify.hashes import Digests, digests_of, side_digests
from fdstoolkit.quality.confidence import ConfidenceReport, score_disk
from fdstoolkit.quality.grade import GradedReport, grade_disk
from fdstoolkit.quality.reads import ReadStatistics, compare_reads
from fdstoolkit.version import VERSION

__version__ = VERSION


def decode_image(data: bytes) -> tuple[Disk, tuple[Diagnostic, ...]]:
    return _decode_fds(data)


def encode_disk(disk: Disk, *, headered: bool = False) -> bytes:
    data, _ = _encode_fds(disk, headered=headered)
    return data


def canonical_digest(disk: Disk, profile: str) -> str:
    return digest_string(canonicalise(disk, profile_by_name(profile)))


__all__ = [
    "Advice",
    "Block",
    "BlockKind",
    "CaptureFormat",
    "CaptureReport",
    "ClassReport",
    "ConfidenceReport",
    "Diagnostic",
    "Digests",
    "Disk",
    "FileKind",
    "FluxCapture",
    "GradedReport",
    "ReadStatistics",
    "Severity",
    "Side",
    "SpeedReport",
    "Verdict",
    "__version__",
    "advise",
    "analyse_capture",
    "canonical_digest",
    "compare_reads",
    "decode_image",
    "detect_format",
    "digests_of",
    "encode_disk",
    "from_cycles",
    "grade_disk",
    "load_capture",
    "measure_classes",
    "measure_speed",
    "measure_stability",
    "score_disk",
    "side_digests",
]
