from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fdstoolkit import doctor as doctor_module
from fdstoolkit.doctor import CheckStatus, DoctorReport, diagnose, firmware_text, load_hid
from fdstoolkit.drive.speed import from_cycles
from fdstoolkit.hardware.fdsstick import PRODUCT_ID, VENDOR_ID
from fdstoolkit.identify.cache import DatCache


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

        def device(self) -> FakeHandle:
            return FakeHandle(None)

    report = diagnose(load_hid=BrokenHid, cache=DatCache(tmp_path))

    assert status_of(report, "fdsstick") is CheckStatus.WARNING
    assert "no backend" in detail_of(report, "fdsstick")


def test_the_real_loader_imports_the_hid_module() -> None:
    try:
        module = load_hid()
    except ImportError:
        return
    assert hasattr(module, "enumerate")


def stick(**extra: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "vendor_id": VENDOR_ID,
        "product_id": PRODUCT_ID,
        "path": b"/dev/hidraw0",
    }
    entry.update(extra)
    return entry


def test_a_connected_stick_is_named_so_a_submission_can_quote_it(tmp_path: Path) -> None:
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

    report = diagnose(load_hid=lambda: hid, cache=DatCache(tmp_path))

    detail = detail_of(report, "fdsstick")
    assert "loopy FDSStick" in detail
    assert "serial 0001" in detail
    assert "firmware 1.04" in detail


def test_a_device_with_no_strings_is_still_reported(tmp_path: Path) -> None:
    hid = FakeHid([stick()])

    report = diagnose(load_hid=lambda: hid, cache=DatCache(tmp_path))

    assert status_of(report, "fdsstick") is CheckStatus.OK
    assert "unnamed device" in detail_of(report, "fdsstick")


def test_a_device_that_opens_is_reported_as_usable(tmp_path: Path) -> None:
    hid = FakeHid([stick()])

    report = diagnose(load_hid=lambda: hid, cache=DatCache(tmp_path))

    assert status_of(report, "fdsstick access") is CheckStatus.OK
    assert hid.handle.closed


def test_a_device_present_but_unopenable_fails_and_names_the_udev_rule(tmp_path: Path) -> None:
    hid = FakeHid([stick()], open_error=PermissionError("Permission denied"))

    report = diagnose(load_hid=lambda: hid, cache=DatCache(tmp_path))

    assert status_of(report, "fdsstick access") is CheckStatus.FAILED
    assert "udev" in detail_of(report, "fdsstick access")
    assert not report.healthy


def test_a_device_with_no_open_path_is_a_warning(tmp_path: Path) -> None:
    hid = FakeHid([stick(path=None)])

    report = diagnose(load_hid=lambda: hid, cache=DatCache(tmp_path))

    assert status_of(report, "fdsstick access") is CheckStatus.WARNING


def test_an_absent_stick_tells_the_operator_to_plug_it_in(tmp_path: Path) -> None:
    report = diagnose(load_hid=lambda: FakeHid([]), cache=DatCache(tmp_path))

    assert "Connect the FDSStick" in detail_of(report, "fdsstick")


def test_the_firmware_reads_as_binary_coded_decimal() -> None:
    assert firmware_text(0x0104) == "1.04"
    assert firmware_text(0x0210) == "2.10"


def test_the_codec_is_proved_by_a_round_trip(tmp_path: Path) -> None:
    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path))

    assert status_of(report, "codec") is CheckStatus.OK
    assert "round-trips" in detail_of(report, "codec")


def test_the_identity_path_is_proved_against_the_published_digests(tmp_path: Path) -> None:
    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path))

    assert status_of(report, "identity") is CheckStatus.OK
    assert "published digests" in detail_of(report, "identity")


def test_the_flux_path_measures_a_synthesised_capture_at_nominal(tmp_path: Path) -> None:
    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path))

    assert status_of(report, "flux") is CheckStatus.OK
    assert "kbit/s" in detail_of(report, "flux")


def test_an_empty_report_has_no_verdict_rather_than_a_healthy_one() -> None:
    empty = DoctorReport(checks=())

    with pytest.raises(ValueError, match="nothing was checked"):
        _ = empty.healthy


def test_every_check_can_report_more_than_one_outcome(tmp_path: Path) -> None:
    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path))

    assert len({check.status for check in report.checks}) > 1


def test_a_codec_that_does_not_round_trip_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def empty_encode(disk: object, *, headered: bool) -> tuple[bytes, tuple[()]]:
        del disk, headered
        return b"", ()

    monkeypatch.setattr("fdstoolkit.doctor.fds.encode", empty_encode)

    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path))

    assert status_of(report, "codec") is CheckStatus.FAILED
    assert "differ" in detail_of(report, "codec")


def test_a_codec_that_raises_is_reported_rather_than_crashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(data: bytes) -> object:
        del data
        message = "the decoder gave up"
        raise ValueError(message)

    monkeypatch.setattr("fdstoolkit.doctor.fds.decode", boom)

    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path))

    assert status_of(report, "codec") is CheckStatus.FAILED
    assert "did not survive" in detail_of(report, "codec")


def test_a_blank_that_misses_its_published_digest_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(doctor_module, "REFERENCE_BLANK_64_SHA256", "0" * 64)

    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path))

    assert status_of(report, "identity") is CheckStatus.FAILED
    assert "not the published" in detail_of(report, "identity")


def test_a_flux_path_that_raises_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(disk: object) -> object:
        del disk
        message = "no capture could be built"
        raise ValueError(message)

    monkeypatch.setattr(doctor_module, "synthesise", boom)

    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path))

    assert status_of(report, "flux") is CheckStatus.FAILED
    assert "did not run" in detail_of(report, "flux")


def test_a_drive_measured_off_the_nominal_rate_is_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def slow(intervals: object) -> object:
        del intervals
        return from_cycles(200)

    monkeypatch.setattr(doctor_module, "measure_speed", slow)

    report = diagnose(load_hid=missing_hid, cache=DatCache(tmp_path))

    assert status_of(report, "flux") is CheckStatus.FAILED
    assert "kbit/s" in detail_of(report, "flux")
