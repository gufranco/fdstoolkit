from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from itertools import pairwise
from typing import Final

from fdstoolkit.codecs.fds import SIDE_SIZE
from fdstoolkit.codecs.raw import decode_raw03
from fdstoolkit.core.blocks import CrcStatus
from fdstoolkit.core.diagnostics import Diagnostic, Severity
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.flux.analysis import analyse_intervals
from fdstoolkit.flux.model import LONG_NS, MEDIUM_NS, SHORT_NS, FluxCapture, FluxTrack

BOUNDARIES: Final[tuple[float, ...]] = (
    (SHORT_NS + MEDIUM_NS) / 2,
    (MEDIUM_NS + LONG_NS) / 2,
    LONG_NS * 1.5,
)
TOP_CLASS: Final = 3
MIN_FIT_PULSES: Final = 64


def classes_from_intervals(
    intervals: Sequence[int],
    *,
    boundaries: Sequence[float] = BOUNDARIES,
) -> bytes:
    out = bytearray()
    for interval in intervals:
        value = TOP_CLASS
        for label, boundary in enumerate(boundaries):
            if interval < boundary:
                value = label
                break
        out.append(value)
    return bytes(out)


def fitted_boundaries(intervals: Sequence[int]) -> tuple[float, ...]:
    if len(intervals) < MIN_FIT_PULSES:
        return BOUNDARIES
    report = analyse_intervals(intervals)
    centres = [cluster.centre_ns for cluster in report.clusters if cluster.count]
    if len(centres) < len(report.clusters):
        return BOUNDARIES
    midpoints = [(low + high) / 2 for low, high in pairwise(centres)]
    return (*midpoints, centres[-1] * 1.5)


def _score(side: Side, findings: Sequence[Diagnostic]) -> tuple[int, int, int]:
    valid = sum(1 for block in side.blocks if block.crc_status is CrcStatus.VALID)
    errors = sum(1 for finding in findings if finding.severity is Severity.ERROR)
    return (len(side.blocks), valid, -errors)


def decode_track(track: FluxTrack, *, adaptive: bool = True) -> tuple[Side, tuple[Diagnostic, ...]]:
    best: tuple[Side, tuple[Diagnostic, ...]] = (
        Side(blocks=(), tail=b"", capacity=0),
        (),
    )
    best_score = (-1, -1, -1)

    for revolution in track.revolutions:
        if not revolution.intervals:
            message = f"track {track.index} holds a revolution with no interval"
            raise ValueError(message)
        options: list[tuple[float, ...]] = [BOUNDARIES]
        if adaptive:
            fitted = fitted_boundaries(revolution.intervals)
            if fitted != BOUNDARIES:
                options.insert(0, fitted)
        for boundaries in options:
            classes = classes_from_intervals(revolution.intervals, boundaries=boundaries)
            side, findings = decode_raw03(classes)
            score = _score(side, findings)
            if score > best_score:
                best, best_score = (side, findings), score

    return best


def decode_capture(
    capture: FluxCapture,
    *,
    adaptive: bool = True,
) -> tuple[Disk, tuple[Diagnostic, ...]]:
    sides: list[Side] = []
    findings: list[Diagnostic] = []

    for track in capture.tracks:
        side, track_findings = decode_track(track, adaptive=adaptive)
        sides.append(Side(blocks=side.blocks, tail=side.tail, capacity=SIDE_SIZE))
        findings.extend(replace(finding, side=track.index) for finding in track_findings)

    return Disk(sides=tuple(sides)), tuple(findings)
