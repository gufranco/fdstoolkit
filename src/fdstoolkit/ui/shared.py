from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterable
from dataclasses import asdict, is_dataclass
from typing import Any, Final, NoReturn

from fastapi import HTTPException

from fdstoolkit.codecs import fds
from fdstoolkit.codecs.foreign import ForeignImageError, reject_foreign
from fdstoolkit.core.diagnostics import Diagnostic
from fdstoolkit.core.disk import Disk
from fdstoolkit.ui.schemas import FileResult

BAD_REQUEST: Final = 400
UNPROCESSABLE: Final = 422


def refuse(message: str, *, status: int = BAD_REQUEST) -> NoReturn:
    raise HTTPException(status_code=status, detail=message)


def bytes_of(payload: str) -> bytes:
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as error:
        message = f"the payload is not base64: {error}"
        raise HTTPException(status_code=BAD_REQUEST, detail=message) from error
    if not data:
        refuse("the payload carries no bytes")
    return data


def decode_payload(payload: str) -> tuple[Disk, bytes, tuple[Diagnostic, ...]]:
    data = bytes_of(payload)
    try:
        reject_foreign(data)
    except ForeignImageError as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    disk, findings = fds.decode(data)
    return disk, data, findings


def encoded(disk: Disk, *, headered: bool = False) -> bytes:
    data, _ = fds.encode(disk, headered=headered)
    return data


def named_file(name: str, data: bytes) -> FileResult:
    return FileResult(
        name=name,
        data=base64.b64encode(data).decode("ascii"),
        size=len(data),
    )


def rows_of(items: Iterable[object]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items:
        if is_dataclass(item) and not isinstance(item, type):
            out.append(json.loads(json.dumps(asdict(item), default=str)))
        elif isinstance(item, dict):
            out.append(json.loads(json.dumps(item, default=str)))
        else:
            out.append({"value": str(item)})
    return out
