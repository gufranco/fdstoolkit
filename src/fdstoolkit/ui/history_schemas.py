from __future__ import annotations

from pydantic import BaseModel, Field

from fdstoolkit.hardware.session import MAX_RETRIES


class LogSpec(BaseModel):
    data: str | None = Field(None, description="an image of the disk whose history to show")
    drive: str | None = Field(
        None, max_length=64, description="the label of the drive whose history to show"
    )


class LogEntryView(BaseModel):
    recorded: str
    kind: str
    grade: str
    title: str
    drive: str | None
    weak: list[list[int]]


class LogResult(BaseModel):
    headline: str
    text: str
    subject: str
    entries: list[LogEntryView]
    weakened: list[list[int]]
    settled: list[list[int]]
    since: str | None
    lines: list[str]


class SessionSpec(BaseModel):
    reference: str | None = Field(
        None, description="an image of the reference disk in the drive, dumped by a drive you trust"
    )
    retries: int = Field(3, ge=0, le=MAX_RETRIES)


class SessionResult(BaseModel):
    headline: str
    ok: bool
    grade: str
    weak: list[list[int]]
    moved: list[list[int]]
    since: str | None
