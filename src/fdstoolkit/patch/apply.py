from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from fdstoolkit.codecs.fds import build_header, decode, has_header
from fdstoolkit.core.diagnostics import Severity, worst_severity
from fdstoolkit.core.disk import HEADER_SIZE, SIDE_SIZE
from fdstoolkit.patch.formats import (
    PatchError,
    PatchFormat,
    apply_bps,
    apply_ips,
    apply_ups,
    detect_format,
)

APPLIERS: Final[dict[PatchFormat, Callable[[bytes, bytes], bytes]]] = {
    PatchFormat.IPS: apply_ips,
    PatchFormat.UPS: apply_ups,
    PatchFormat.BPS: apply_bps,
}


@dataclass(frozen=True, slots=True)
class PatchOutcome:
    data: bytes
    format: PatchFormat
    applied_to: str
    header_restored: bool


def _parses_cleanly(data: bytes) -> bool:
    _, findings = decode(data)
    return worst_severity(findings) is not Severity.ERROR


def _restore_header(data: bytes) -> bytes:
    sides = max(1, len(data) // SIDE_SIZE)
    return build_header(sides) + data


NO_LONGER_PARSES: Final = "the patched image no longer parses as a disk image"

Applier = Callable[[bytes, bytes], bytes]


def _direct(
    applier: Applier, kind: PatchFormat, patch: bytes, image: bytes
) -> PatchOutcome | PatchError:
    try:
        direct = applier(patch, image)
    except PatchError as error:
        return error
    if kind is not PatchFormat.IPS or _parses_cleanly(direct):
        return PatchOutcome(data=direct, format=kind, applied_to="image", header_restored=False)
    return PatchError(NO_LONGER_PARSES)


def _headerless(applier: Applier, kind: PatchFormat, patch: bytes, body: bytes) -> PatchOutcome:
    patched = applier(patch, body)
    if kind is PatchFormat.IPS and not _parses_cleanly(patched):
        raise PatchError(NO_LONGER_PARSES)
    return PatchOutcome(
        data=_restore_header(patched),
        format=kind,
        applied_to="headerless image",
        header_restored=True,
    )


def apply_patch(patch: bytes, image: bytes) -> PatchOutcome:
    kind = detect_format(patch)
    applier = APPLIERS.get(kind)
    if applier is None:
        message = "unknown patch format, expected IPS, UPS or BPS"
        raise PatchError(message)
    attempt = _direct(applier, kind, patch, image)
    if isinstance(attempt, PatchOutcome):
        return attempt
    if not has_header(image):
        raise attempt
    return _headerless(applier, kind, patch, image[HEADER_SIZE:])
