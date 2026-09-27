from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final

from fdstoolkit.codecs.raw import (
    LEAD_IN_BITS,
    NOMINAL_LONG,
    NOMINAL_MEDIUM,
    NOMINAL_SHORT,
    encode_block_stream,
    unpack_raw03,
)
from fdstoolkit.core.disk import Side

NOMINALS: Final = (NOMINAL_SHORT, NOMINAL_MEDIUM, NOMINAL_LONG)
COUNT_CEILING: Final = 0xFF
STRAY_COUNT: Final = 0xF0
TRAILING_GAP: Final = 4000


@dataclass(frozen=True, slots=True)
class DriveModel:
    speed: float = 1.0
    jitter: int = 2
    strays: int = 0
    lead_in: int = LEAD_IN_BITS
    seed: int = 0


def side_classes(side: Side, *, lead_in: int = LEAD_IN_BITS) -> bytes:
    values = unpack_raw03(encode_block_stream([block.payload for block in side.blocks]))
    return bytes(lead_in) + values[LEAD_IN_BITS:] + bytes(TRAILING_GAP)


def _stray_positions(classes: bytes, model: DriveModel) -> frozenset[int]:
    data = [index for index, value in enumerate(classes) if value and index > model.lead_in]
    if not model.strays:
        return frozenset()
    step = max(len(data) // model.strays, 1)
    return frozenset(data[::step][: model.strays])


def drive_counts(side: Side, model: DriveModel) -> bytes:
    classes = side_classes(side, lead_in=model.lead_in)
    noise = hashlib.shake_256(model.seed.to_bytes(4, "little")).digest(len(classes))
    strays = _stray_positions(classes, model)
    spread = 2 * model.jitter + 1
    return bytes(
        STRAY_COUNT
        if index in strays
        else min(
            COUNT_CEILING,
            max(1, round(NOMINALS[value] / model.speed) + offset % spread - model.jitter),
        )
        for index, (value, offset) in enumerate(zip(classes, noise, strict=True))
    )
