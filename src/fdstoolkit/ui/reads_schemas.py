from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field

from fdstoolkit.core.disk import SIDES_PER_DISK
from fdstoolkit.drive.recognition import ReadRate


class WeakView(BaseModel):
    side: int
    block: int
    kind: str
    unstable: int
    invalid: int
    reads: int
    missing: int


class RateView(BaseModel):
    side: int
    read: int
    rate: float
    counted: int
    unclassed: int
    span: str

    @classmethod
    def of(cls, found: ReadRate) -> Self:
        return cls(
            side=found.side,
            read=found.read,
            rate=found.recognition.rate,
            counted=found.recognition.counted,
            unclassed=found.recognition.unclassed,
            span=found.recognition.span.value,
        )


class WeakResult(BaseModel):
    reads: int
    rates: list[RateView]
    weak: list[WeakView]


class TrackSpec(BaseModel):
    captures: str = Field(description="the capture bundle a dump kept, as a zip")
    side: int = Field(0, ge=0, le=SIDES_PER_DISK - 1)


class BinView(BaseModel):
    start: int
    end: int
    classes: list[int]


class TrackBlockView(BaseModel):
    index: int
    kind: str
    start: int
    end: int
    weak: bool
    unstable: int
    invalid: int
    missing: int
    label: str


class TrackResult(BaseModel):
    headline: str
    side: int
    reads: int
    length: int
    bins: list[BinView]
    blocks: list[TrackBlockView]
