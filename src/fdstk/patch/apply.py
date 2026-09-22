from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fdstk.codecs.fds import HEADER_SIZE, SIDE_SIZE, build_header, decode, has_header
from fdstk.core.diagnostics import Severity, worst_severity
from fdstk.patch.formats import (
    PatchError,
    PatchFormat,
    apply_bps,
    apply_ips,
    apply_ups,
    detect_format,
)

APPLIERS: dict[PatchFormat, Callable[[bytes, bytes], bytes]] = {
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


def apply_patch(patch: bytes, image: bytes) -> PatchOutcome:
    kind = detect_format(patch)
    applier = APPLIERS.get(kind)
    if applier is None:
        message = "unknown patch format, expected IPS, UPS or BPS"
        raise PatchError(message)

    headered = has_header(image)
    body = image[HEADER_SIZE:] if headered else image

    direct_error: PatchError | None = None
    try:
        direct = applier(patch, image)
    except PatchError as error:
        direct_error = error
    else:
        if kind is not PatchFormat.IPS or _parses_cleanly(direct):
            return PatchOutcome(
                data=direct,
                format=kind,
                applied_to="image",
                header_restored=False,
            )

    if not headered:
        if direct_error is not None:
            raise direct_error
        message = "the patched image no longer parses as a disk image"
        raise PatchError(message)

    patched_body = applier(patch, body)
    if kind is PatchFormat.IPS and not _parses_cleanly(patched_body):
        message = "the patched image no longer parses as a disk image"
        raise PatchError(message)

    return PatchOutcome(
        data=_restore_header(patched_body),
        format=kind,
        applied_to="headerless image",
        header_restored=True,
    )
