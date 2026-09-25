from __future__ import annotations

from fdstoolkit.codecs.fds import decode as _decode_fds
from fdstoolkit.codecs.fds import encode as _encode_fds
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.canon import canonicalise, digest_string, profile_by_name
from fdstoolkit.core.diagnostics import Diagnostic, Severity
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.drive.monitor import Calibration, SideSample, calibrate
from fdstoolkit.drive.monitor import Mode as CalibrationMode
from fdstoolkit.drive.monitor import sample as sample_side
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
    "Block",
    "BlockKind",
    "Calibration",
    "CalibrationMode",
    "ConfidenceReport",
    "Diagnostic",
    "Digests",
    "Disk",
    "FileKind",
    "GradedReport",
    "ReadStatistics",
    "Severity",
    "Side",
    "SideSample",
    "__version__",
    "calibrate",
    "canonical_digest",
    "compare_reads",
    "decode_image",
    "digests_of",
    "encode_disk",
    "grade_disk",
    "sample_side",
    "score_disk",
    "side_digests",
]
