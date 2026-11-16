from __future__ import annotations

from pydantic import BaseModel, Field

from fdstoolkit.core.disk import SIDES_PER_DISK
from fdstoolkit.hardware.session import MAX_PASSES, MAX_RETRIES
from fdstoolkit.ui.schemas import SideCount


class EraseSpec(BaseModel):
    sides: SideCount = 1
    retries: int = Field(3, ge=0, le=MAX_RETRIES)
    confirm: bool = False


class DuplicateSpec(BaseModel):
    data: str
    count: int = Field(1, ge=1, le=100)
    retries: int = Field(3, ge=0, le=MAX_RETRIES)
    confirm: bool = False


class RefreshSpec(BaseModel):
    sides: SideCount = 1
    passes: int = Field(3, ge=1, le=MAX_PASSES)
    retries: int = Field(3, ge=0, le=MAX_RETRIES)
    confirm: bool = False


class SaveBackupSpec(BaseModel):
    side: int = Field(0, ge=0, le=SIDES_PER_DISK - 1)
    file: int | None = Field(None, ge=0, le=255)
    retries: int = Field(3, ge=0, le=MAX_RETRIES)


class SaveRestoreSpec(BaseModel):
    saved: str = Field(description="a save kept by save-backup")
    retries: int = Field(3, ge=0, le=MAX_RETRIES)
    confirm: bool = False
