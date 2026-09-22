from __future__ import annotations

import random
from typing import Final

from fdstoolkit.codecs.raw import encode_raw03, unpack_raw03
from fdstoolkit.core.disk import Disk
from fdstoolkit.flux.model import (
    LONG_NS,
    MEDIUM_NS,
    SHORT_NS,
    FluxCapture,
    FluxTrack,
    Revolution,
    Source,
)

MAX_SYNTH_CLASS: Final = 2
CLASS_NS: Final = (SHORT_NS, MEDIUM_NS, LONG_NS)


def intervals_from_classes(
    values: bytes,
    *,
    jitter_ns: int = 0,
    seed: int | None = None,
) -> tuple[int, ...]:
    if any(value > MAX_SYNTH_CLASS for value in values):
        message = f"a synthesised pulse class is between 0 and {MAX_SYNTH_CLASS}"
        raise ValueError(message)
    clean = [CLASS_NS[value] for value in values]
    if not jitter_ns:
        return tuple(clean)
    noise = random.Random(seed)  # noqa: S311
    return tuple(value + noise.randint(-jitter_ns, jitter_ns) for value in clean)


def synthesise(
    disk: Disk,
    *,
    revolutions: int = 1,
    jitter_ns: int = 0,
    seed: int | None = None,
) -> FluxCapture:
    if revolutions < 1:
        message = "a capture needs at least one revolution"
        raise ValueError(message)

    tracks: list[FluxTrack] = []
    for index in range(disk.side_count):
        classes = unpack_raw03(encode_raw03(disk, side=index))
        spins = tuple(
            Revolution(
                intervals=intervals_from_classes(
                    classes,
                    jitter_ns=jitter_ns,
                    seed=None if seed is None else seed + index * revolutions + spin,
                )
            )
            for spin in range(revolutions)
        )
        tracks.append(FluxTrack(index=index, revolutions=spins))

    return FluxCapture(source=Source.SYNTHETIC, tracks=tuple(tracks))
