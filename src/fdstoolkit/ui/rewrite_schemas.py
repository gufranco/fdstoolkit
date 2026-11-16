from __future__ import annotations

from pydantic import BaseModel, Field

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
