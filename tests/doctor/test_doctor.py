from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from fdstoolkit import doctor as doctor_module
from fdstoolkit.core.diagnostics import Diagnostic
from fdstoolkit.core.disk import Disk
from fdstoolkit.doctor import (
    CheckStatus,
    DoctorReport,
    codec_check,
    diagnose,
    firmware_text,
    load_hid,
)
from fdstoolkit.hardware.device_lock import acquire_drive_lock
from fdstoolkit.hardware.fdsstick import PRODUCT_ID, VENDOR_ID


class FakeHandle:
    def __init__(self, error: OSError | None) -> None:
        self._error = error
        self.closed = False

    def open_path(self, path: bytes) -> None:
        del path
        if self._error is not None:
            raise self._error

    def close(self) -> None:
        self.closed = True


class FakeHid:
    def __init__(
        self,
        devices: list[dict[str, Any]],
        *,
        open_error: OSError | None = None,
    ) -> None:
        self._devices = devices
        self._open_error = open_error
        self.handle = FakeHandle(open_error)

    def device(self) -> FakeHandle:
        return self.handle

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


def test_the_version_and_the_interpreter_are_reported() -> None:
    # Arrange
    expected = CheckStatus.OK

    # Act
    report = diagnose(load_hid=missing_hid)

    # Assert
    assert status_of(report, "fdstoolkit") is expected
    assert status_of(report, "python") is CheckStatus.OK


def test_a_missing_hardware_extra_is_reported_with_the_fix() -> None:
    # Arrange
    load_hid = missing_hid

    # Act
    report = diagnose(load_hid=load_hid)

    # Assert
    assert status_of(report, "hardware support") is CheckStatus.MISSING
    assert "brew reinstall gufranco/tap/fdstoolkit" in detail_of(report, "hardware support")


def test_no_connected_fdsstick_is_a_warning_not_a_failure() -> None:
    # Arrange
    expected = CheckStatus.OK

    # Act
    report = diagnose(load_hid=lambda: FakeHid([]))

    # Assert
    assert status_of(report, "hardware support") is expected
    assert status_of(report, "fdsstick") is CheckStatus.WARNING


def test_a_connected_fdsstick_is_found() -> None:
    # Arrange
    device = {"vendor_id": VENDOR_ID, "product_id": PRODUCT_ID}

    # Act
    report = diagnose(load_hid=lambda: FakeHid([device]))

    # Assert
    assert status_of(report, "fdsstick") is CheckStatus.OK
    assert "1 device" in detail_of(report, "fdsstick")


def test_the_fdsstick_check_is_skipped_without_the_extra() -> None:
    # Arrange
    expected = CheckStatus.MISSING

    # Act
    report = diagnose(load_hid=missing_hid)

    # Assert
    assert status_of(report, "fdsstick") is expected


def test_an_old_interpreter_is_a_failure() -> None:
    # Arrange
    python = (3, 11, 9)

    # Act
    report = diagnose(load_hid=missing_hid, python=python)

    # Assert
    assert status_of(report, "python") is CheckStatus.FAILED
    assert not report.healthy


def test_a_report_with_only_warnings_is_healthy() -> None:
    # Arrange
    hid = FakeHid([])

    # Act
    report = diagnose(load_hid=lambda: hid)

    # Assert
    assert report.healthy


def test_a_usb_stack_that_cannot_list_devices_is_a_warning() -> None:
    # Arrange
    class BrokenHid:
        def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, Any]]:
            del vendor_id, product_id
            message = "no backend"
            raise OSError(message)

        def device(self) -> FakeHandle:
            return FakeHandle(None)

    # Act
    report = diagnose(load_hid=BrokenHid)

    # Assert
    assert status_of(report, "fdsstick") is CheckStatus.WARNING
    assert "no backend" in detail_of(report, "fdsstick")


def test_the_real_loader_imports_the_hid_module(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    module = FakeHid([])
    monkeypatch.setitem(sys.modules, "hid", module)

    # Act
    loaded = load_hid()

    # Assert
    assert loaded is module


def stick(**extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "vendor_id": VENDOR_ID,
        "product_id": PRODUCT_ID,
        "path": b"/dev/hidraw0",
    }
    entry.update(extra)
    return entry


def test_a_connected_stick_is_named_so_a_submission_can_quote_it() -> None:
    # Arrange
    hid = FakeHid(
        [
            stick(
                manufacturer_string="loopy",
                product_string="FDSStick",
                serial_number="0001",
                release_number=0x0104,
            )
        ]
    )
    report = diagnose(load_hid=lambda: hid)

    # Act
    detail = detail_of(report, "fdsstick")

    # Assert
    assert "loopy FDSStick" in detail
    assert "serial 0001" in detail
    assert "firmware 1.04" in detail


def test_a_device_with_no_strings_is_still_reported() -> None:
    # Arrange
    hid = FakeHid([stick()])

    # Act
    report = diagnose(load_hid=lambda: hid)

    # Assert
    assert status_of(report, "fdsstick") is CheckStatus.OK
    assert "unnamed device" in detail_of(report, "fdsstick")


def test_a_device_that_opens_is_reported_as_usable() -> None:
    # Arrange
    hid = FakeHid([stick()])

    # Act
    report = diagnose(load_hid=lambda: hid)

    # Assert
    assert status_of(report, "fdsstick access") is CheckStatus.OK
    assert hid.handle.closed


class CountingHandle(FakeHandle):
    def __init__(self) -> None:
        super().__init__(None)
        self.opened = 0

    def open_path(self, path: bytes) -> None:
        del path
        self.opened += 1


def test_a_drive_another_job_holds_is_not_opened_to_check_it() -> None:
    # Arrange
    hid = FakeHid([stick()])
    handle = CountingHandle()
    hid.handle = handle
    held = acquire_drive_lock()
    report = diagnose(load_hid=lambda: hid)

    # Act
    held.release()

    # Assert
    assert handle.opened == 0
    assert status_of(report, "fdsstick access") is CheckStatus.OK
    assert "in use" in detail_of(report, "fdsstick access")


def test_a_drive_lock_this_user_cannot_open_fails_the_access_check(tmp_path: Path) -> None:
    # Arrange
    locked = tmp_path / "drive.lock"
    locked.write_bytes(b"")
    locked.chmod(0)
    hid = FakeHid([stick()])
    report = diagnose(load_hid=lambda: hid, lock_path=locked)

    # Act
    locked.chmod(0o600)

    # Assert
    assert status_of(report, "fdsstick access") is CheckStatus.FAILED
    assert "cannot open the drive lock" in detail_of(report, "fdsstick access")


def test_a_device_present_but_unopenable_fails_and_names_the_udev_rule() -> None:
    # Arrange
    hid = FakeHid([stick()], open_error=PermissionError("Permission denied"))

    # Act
    report = diagnose(load_hid=lambda: hid)

    # Assert
    assert status_of(report, "fdsstick access") is CheckStatus.FAILED
    assert "udev" in detail_of(report, "fdsstick access")
    assert not report.healthy


def test_a_device_with_no_open_path_is_a_warning() -> None:
    # Arrange
    hid = FakeHid([stick(path=None)])

    # Act
    report = diagnose(load_hid=lambda: hid)

    # Assert
    assert status_of(report, "fdsstick access") is CheckStatus.WARNING


def test_an_absent_stick_tells_the_operator_to_plug_it_in() -> None:
    # Arrange
    hid = FakeHid([])

    # Act
    report = diagnose(load_hid=lambda: hid)

    # Assert
    assert "Connect the FDSStick" in detail_of(report, "fdsstick")


def test_the_firmware_reads_as_binary_coded_decimal() -> None:
    # Arrange
    release = 0x0104

    # Act
    result = firmware_text(release)

    # Assert
    assert result == "1.04"
    assert firmware_text(0x0210) == "2.10"


def test_the_codec_is_proved_by_a_round_trip() -> None:
    # Arrange
    expected = CheckStatus.OK

    # Act
    report = diagnose(load_hid=missing_hid)

    # Assert
    assert status_of(report, "codec") is expected
    assert "round-trips" in detail_of(report, "codec")


def test_the_identity_path_is_proved_against_the_published_digests() -> None:
    # Arrange
    expected = CheckStatus.OK

    # Act
    report = diagnose(load_hid=missing_hid)

    # Assert
    assert status_of(report, "identity") is expected
    assert "published digests" in detail_of(report, "identity")


def test_an_empty_report_has_no_verdict_rather_than_a_healthy_one() -> None:
    # Arrange
    empty = DoctorReport(checks=())

    # Act
    with pytest.raises(ValueError, match="nothing was checked") as raised:
        _ = empty.healthy

    # Assert
    assert raised.type is ValueError


def test_every_check_can_report_more_than_one_outcome() -> None:
    # Arrange
    expected = 1

    # Act
    report = diagnose(load_hid=missing_hid)

    # Assert
    assert len({check.status for check in report.checks}) > expected


def test_a_codec_that_does_not_round_trip_is_reported() -> None:
    # Arrange
    def empty_encode(disk: object, *, headered: bool) -> tuple[bytes, tuple[()]]:
        del disk, headered
        return b"", ()

    # Act
    check = codec_check(encode=empty_encode)

    # Assert
    assert check.status is CheckStatus.FAILED
    assert "differ" in check.detail


def test_a_codec_that_raises_is_reported_rather_than_crashing() -> None:
    # Arrange
    def boom(data: bytes) -> tuple[Disk, tuple[Diagnostic, ...]]:
        del data
        message = "the decoder gave up"
        raise ValueError(message)

    # Act
    check = codec_check(decode=boom)

    # Assert
    assert check.status is CheckStatus.FAILED
    assert "did not survive" in check.detail


def test_a_blank_that_misses_its_published_digest_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Arrange
    monkeypatch.setattr(doctor_module, "REFERENCE_BLANK_64_SHA256", "0" * 64)

    # Act
    report = diagnose(load_hid=missing_hid)

    # Assert
    assert status_of(report, "identity") is CheckStatus.FAILED
    assert "not the published" in detail_of(report, "identity")
