from __future__ import annotations

import hashlib
import importlib
import platform
import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol, cast

from fdstoolkit.build.blank import (
    REFERENCE_BLANK_64_SHA256,
    REFERENCE_BLANK_128_SHA256,
    blank_image,
)
from fdstoolkit.codecs import fds
from fdstoolkit.hardware.fdsstick import PRODUCT_ID, VENDOR_ID
from fdstoolkit.identify.cache import DatCache
from fdstoolkit.version import VERSION

MIN_PYTHON: Final = (3, 12)
HARDWARE_HINT: Final = (
    "Homebrew installs it with the toolkit: brew reinstall gufranco/fdstoolkit/fdstoolkit"
)
UDEV_HINT: Final = (
    "the device is present but cannot be opened, which on Linux means a missing udev rule: "
    'write SUBSYSTEM=="hidraw", ATTRS{idVendor}=="16d0", ATTRS{idProduct}=="0aaa", MODE="0666" '
    "to /etc/udev/rules.d/99-fdsstick.rules and reload"
)
BCD_MAJOR_SHIFT: Final = 8
BCD_MASK: Final = 0xFF
SELF_TEST_SIDES: Final = 1


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
        if not self.checks:
            message = "nothing was checked, so there is no verdict to give"
            raise ValueError(message)
        return all(check.status is not CheckStatus.FAILED for check in self.checks)


class Opener(Protocol):
    def open_path(self, path: bytes) -> None: ...

    def close(self) -> None: ...


class Enumerator(Protocol):
    def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, Any]]: ...

    def device(self) -> Opener: ...


def load_hid() -> Enumerator:
    return cast("Enumerator", importlib.import_module("hid"))


def firmware_text(release: int) -> str:
    major = (release >> BCD_MAJOR_SHIFT) & BCD_MASK
    minor = release & BCD_MASK
    return f"{major:x}.{minor:02x}"


def _describe(entry: dict[str, Any]) -> str:
    maker = str(entry.get("manufacturer_string") or "").strip()
    product = str(entry.get("product_string") or "").strip()
    serial = str(entry.get("serial_number") or "").strip()
    parts = [part for part in (maker, product) if part]
    name = " ".join(parts) if parts else "unnamed device"
    if serial:
        name = f"{name}, serial {serial}"
    release = entry.get("release_number")
    if isinstance(release, int) and release:
        name = f"{name}, firmware {firmware_text(release)}"
    return name


def _access_check(hid: Enumerator, entry: dict[str, Any]) -> Check:
    path = entry.get("path")
    if not isinstance(path, bytes):
        return Check("fdsstick access", CheckStatus.WARNING, "the device reported no open path")
    try:
        handle = hid.device()
        handle.open_path(path)
    except OSError as error:
        return Check("fdsstick access", CheckStatus.FAILED, f"{error}. {UDEV_HINT}")
    handle.close()
    return Check("fdsstick access", CheckStatus.OK, "the device opens for reading and writing")


def _python_check(version: tuple[int, int, int]) -> Check:
    text = ".".join(str(part) for part in version)
    if version[:2] < MIN_PYTHON:
        wanted = ".".join(str(part) for part in MIN_PYTHON)
        return Check("python", CheckStatus.FAILED, f"{text}, and {wanted} or newer is required")
    return Check("python", CheckStatus.OK, text)


def hardware_checks(loader: Callable[[], Enumerator] = load_hid) -> tuple[Check, ...]:
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
            f"none connected at {VENDOR_ID:04X}:{PRODUCT_ID:04X}. "
            "Connect the FDSStick over USB before dumping or writing",
        )

    first = found[0]
    present = Check(
        "fdsstick",
        CheckStatus.OK,
        f"{len(found)} device(s) connected, {_describe(first)}",
    )
    return support, present, _access_check(hid, first)


def _codec_check() -> Check:
    built = blank_image(sides=SELF_TEST_SIDES, headered=False, formatted=True, game_name="TST")
    try:
        disk, findings = fds.decode(built)
        again, _ = fds.encode(disk, headered=False)
    except (ValueError, OSError) as error:
        return Check(
            "codec", CheckStatus.FAILED, f"a known disk did not survive a round trip: {error}"
        )
    if again != built:
        return Check(
            "codec",
            CheckStatus.FAILED,
            f"a known disk re-encoded to {len(again)} bytes, "
            f"which differ from the {len(built)} written",
        )
    blocks = len(disk.sides[0].blocks)
    return Check(
        "codec",
        CheckStatus.OK,
        f"a known disk round-trips to the same {len(built)} bytes, {blocks} blocks, "
        f"{len(findings)} finding(s)",
    )


def _identity_check() -> Check:
    expected = ((1, REFERENCE_BLANK_64_SHA256), (2, REFERENCE_BLANK_128_SHA256))
    for sides, reference in expected:
        built = blank_image(sides=sides, headered=True, formatted=False)
        digest = hashlib.sha256(built).hexdigest()
        if digest != reference:
            return Check(
                "identity",
                CheckStatus.FAILED,
                f"a {sides}-side blank hashed to {digest[:16]}, not the published {reference[:16]}",
            )
    return Check(
        "identity",
        CheckStatus.OK,
        f"{len(expected)} blanks match their published digests",
    )


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
    return DoctorReport(
        checks=(
            Check("fdstoolkit", CheckStatus.OK, VERSION),
            _python_check(interpreter),
            Check("platform", CheckStatus.OK, f"{platform.system()} {platform.machine()}"),
            *hardware_checks(load_hid),
            _codec_check(),
            _identity_check(),
            _cache_check(cache if cache is not None else DatCache()),
        )
    )
