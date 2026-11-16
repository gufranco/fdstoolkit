from __future__ import annotations

from pydantic import BaseModel, Field

from fdstoolkit.hardware.session import MAX_RETRIES
from fdstoolkit.ui.schemas import SideCount


class EraseSpec(BaseModel):
    sides: SideCount = 1
    retries: int = Field(3, ge=0, le=MAX_RETRIES)
    confirm: bool = False
