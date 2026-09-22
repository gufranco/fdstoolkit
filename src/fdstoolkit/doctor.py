from __future__ import annotations

import importlib
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol, cast

from fdstoolkit.hardware.fdsstick import PRODUCT_ID, VENDOR_ID
from fdstoolkit.identify.cache import DatCache
from fdstoolkit.version import VERSION

MIN_PYTHON: Final = (3, 12)
HARDWARE_HINT: Final = "install the hardware extra: uv tool install 'fdstoolkit[hardware]'"


class CheckStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    MISSING = "missing"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    status: CheckStatus
    detail: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[Check, ...]

    @property
    def healthy(self) -> bool:
        return all(check.status is not CheckStatus.FAILED for check in self.checks)


class Enumerator(Protocol):
    def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, Any]]: ...


def load_hid() -> Enumerator:
    return cast("Enumerator", importlib.import_module("hid"))


def _python_check(version: tuple[int, int, int]) -> Check:
    text = ".".join(str(part) for part in version)
    if version[:2] < MIN_PYTHON:
        wanted = ".".join(str(part) for part in MIN_PYTHON)
        return Check("python", CheckStatus.FAILED, f"{text}, and {wanted} or newer is required")
    return Check("python", CheckStatus.OK, text)


def _hardware_checks(loader: Callable[[], Enumerator]) -> tuple[Check, Check]:
    try:
        hid = loader()
    except ImportError:
        return (
            Check("hardware support", CheckStatus.MISSING, f"hidapi is absent, {HARDWARE_HINT}"),
            Check("fdsstick", CheckStatus.MISSING, "not looked for, hidapi is absent"),
        )

    support = Check("hardware support", CheckStatus.OK, "hidapi is installed")
    try:
        found = hid.enumerate(VENDOR_ID, PRODUCT_ID)
    except OSError as error:
        return support, Check(
            "fdsstick", CheckStatus.WARNING, f"could not list USB devices: {error}"
        )
    if not found:
        return support, Check(
            "fdsstick",
            CheckStatus.WARNING,
            f"none connected at {VENDOR_ID:04X}:{PRODUCT_ID:04X}",
        )
    return support, Check("fdsstick", CheckStatus.OK, f"{len(found)} device(s) connected")


def _cache_check(cache: DatCache) -> Check:
    count = len(list(cache.entries()))
    return Check("dat cache", CheckStatus.OK, f"{cache.root}, {count} catalogue(s)")


def diagnose(
    *,
    load_hid: Callable[[], Enumerator] = load_hid,
    cache: DatCache | None = None,
    python: tuple[int, int, int] | None = None,
) -> DoctorReport:
    interpreter = python if python is not None else sys.version_info[:3]
    support, stick = _hardware_checks(load_hid)
    return DoctorReport(
        checks=(
            Check("fdstoolkit", CheckStatus.OK, VERSION),
            _python_check(interpreter),
            Check("platform", CheckStatus.OK, f"{platform.system()} {platform.machine()}"),
            support,
            stick,
            _cache_check(cache if cache is not None else DatCache()),
        )
    )
