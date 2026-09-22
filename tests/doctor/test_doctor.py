from __future__ import annotations

from pathlib import Path
from typing import Any

from fdstoolkit.doctor import CheckStatus, diagnose, load_hid
from fdstoolkit.hardware.fdsstick import PRODUCT_ID, VENDOR_ID
from fdstoolkit.identify.cache import DatCache


class FakeHid:
    def __init__(self, devices: list[dict[str, Any]]) -> None:
        self._devices = devices

    def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, Any]]:
        return [
            device
            for device in self._devices
            if device["vendor_id"] == vendor_id and device["product_id"] == product_id
        ]


def missing_hid() -> FakeHid:
    raise ImportError


def status_of(report: Any, name: str) -> CheckStatus:
    return next(check.status for check in report.checks if check.name == name)


def detail_of(report: Any, name: str) -> str:
    return next(check.detail for check in report.checks if check.name == name)


def test_the_version_and_the_interpreter_are_reported(tmp_path: Path) -> None:
    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path))

    assert status_of(report, "fdstoolkit") is CheckStatus.OK
    assert status_of(report, "python") is CheckStatus.OK


def test_a_missing_hardware_extra_is_reported_with_the_fix(tmp_path: Path) -> None:
    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path))

    assert status_of(report, "hardware support") is CheckStatus.MISSING
    assert "fdstoolkit[hardware]" in detail_of(report, "hardware support")


def test_no_connected_fdsstick_is_a_warning_not_a_failure(tmp_path: Path) -> None:
    report = diagnose(load_hid=lambda: FakeHid([]), cache=DatCache(tmp_path))

    assert status_of(report, "hardware support") is CheckStatus.OK
    assert status_of(report, "fdsstick") is CheckStatus.WARNING


def test_a_connected_fdsstick_is_found(tmp_path: Path) -> None:
    device = {"vendor_id": VENDOR_ID, "product_id": PRODUCT_ID}

    report = diagnose(load_hid=lambda: FakeHid([device]), cache=DatCache(tmp_path))

    assert status_of(report, "fdsstick") is CheckStatus.OK
    assert "1 device" in detail_of(report, "fdsstick")


def test_the_fdsstick_check_is_skipped_without_the_extra(tmp_path: Path) -> None:
    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path))

    assert status_of(report, "fdsstick") is CheckStatus.MISSING


def test_the_dat_cache_location_and_size_are_reported(tmp_path: Path) -> None:
    (tmp_path / "v1-abc.json").write_text("{}", encoding="utf-8")

    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path))

    assert str(tmp_path) in detail_of(report, "dat cache")
    assert "1 catalogue" in detail_of(report, "dat cache")


def test_an_old_interpreter_is_a_failure(tmp_path: Path) -> None:
    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path), python=(3, 11, 9))

    assert status_of(report, "python") is CheckStatus.FAILED
    assert not report.healthy


def test_a_report_with_only_warnings_is_healthy(tmp_path: Path) -> None:
    report = diagnose(load_hid=lambda: FakeHid([]), cache=DatCache(tmp_path))

    assert report.healthy


def test_a_usb_stack_that_cannot_list_devices_is_a_warning(tmp_path: Path) -> None:
    class BrokenHid:
        def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, Any]]:
            del vendor_id, product_id
            message = "no backend"
            raise OSError(message)

    report = diagnose(load_hid=BrokenHid, cache=DatCache(tmp_path))

    assert status_of(report, "fdsstick") is CheckStatus.WARNING
    assert "no backend" in detail_of(report, "fdsstick")


def test_the_real_loader_imports_the_hid_module() -> None:
    try:
        module = load_hid()
    except ImportError:
        return
    assert hasattr(module, "enumerate")
