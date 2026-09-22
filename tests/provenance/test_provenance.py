from __future__ import annotations

from fdstk.build.blank import blank_image
from fdstk.codecs.fds import decode
from fdstk.core.disk import Disk
from fdstk.identify.provenance import Origin, provenance_of


def disk_with_info(**overrides: bytes) -> Disk:
    raw = bytearray(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    for offset, value in overrides.items():
        start = int(offset[1:], 16)
        raw[start : start + len(value)] = value
    disk, _ = decode(bytes(raw))
    return disk


def test_a_factory_disk_reports_no_rewrite() -> None:
    report = provenance_of(disk_with_info(x1F=bytes([0x61, 0x02, 0x15])))

    assert report.sides[0].origin is Origin.FACTORY
    assert report.sides[0].rewrite_count == 0
    assert report.sides[0].writer_serial == 0


def test_a_kiosk_disk_reports_its_rewrite() -> None:
    report = provenance_of(
        disk_with_info(
            x1F=bytes([0x61, 0x02, 0x15]),
            x2C=bytes([0x63, 0x08, 0x01]),
            x31=bytes([0x34, 0x12]),
            x34=bytes([0x03]),
        )
    )

    side = report.sides[0]

    assert side.origin is Origin.REWRITTEN
    assert side.manufacturing_date == (1986, 2, 15)
    assert side.rewritten_date == (1988, 8, 1)
    assert side.writer_serial == 0x1234
    assert side.rewrite_count == 3


def test_a_disk_whose_dates_are_not_valid_bcd_is_flagged() -> None:
    report = provenance_of(disk_with_info(x1F=bytes([0xAB, 0x02, 0x15])))

    assert report.sides[0].manufacturing_date is None
    assert "manufacturing date" in " ".join(report.sides[0].notes)


def test_a_rewrite_count_that_is_not_bcd_is_flagged() -> None:
    report = provenance_of(disk_with_info(x34=bytes([0xAF])))

    assert report.sides[0].rewrite_count is None
    assert "rewrite count" in " ".join(report.sides[0].notes)


def test_a_rewritten_disk_without_a_serial_is_noted() -> None:
    report = provenance_of(
        disk_with_info(x2C=bytes([0x63, 0x08, 0x01]), x34=bytes([0x02])),
    )

    assert "no Disk Writer serial" in " ".join(report.sides[0].notes)


def test_an_unformatted_side_has_no_provenance() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=False))

    report = provenance_of(disk)

    assert report.sides[0].origin is Origin.UNKNOWN
    assert report.sides[0].manufacturing_date is None


def test_the_report_covers_every_side() -> None:
    disk, _ = decode(blank_image(sides=4, headered=False, formatted=True))

    assert len(provenance_of(disk).sides) == 4


def test_the_report_renders_as_data() -> None:
    record = provenance_of(disk_with_info(x34=bytes([0x02]))).sides[0].as_dict()

    assert record["rewrite_count"] == 2
    assert record["origin"] == "rewritten"
    assert list(record) == sorted(record)


def test_a_rewritten_date_that_is_not_bcd_is_flagged() -> None:
    report = provenance_of(disk_with_info(x2C=bytes([0xAB, 0x02, 0x15]), x34=bytes([0x01])))

    assert report.sides[0].rewritten_date is None
    assert "rewritten date" in " ".join(report.sides[0].notes)


def test_a_disk_with_a_serial_but_no_rewrite_count_is_flagged() -> None:
    report = provenance_of(disk_with_info(x31=bytes([0x34, 0x12]), x34=bytes([0x00])))

    assert report.sides[0].origin is Origin.REWRITTEN
    assert "rewrite count is zero" in " ".join(report.sides[0].notes)


def test_a_signature_written_over_the_provenance_region_is_reported() -> None:
    report = provenance_of(disk_with_info(x20=b"hCON by hal9999"))

    assert report.sides[0].signature == "hCON by hal9999"
    assert any("readable text" in note for note in report.sides[0].notes)


def test_a_clean_provenance_region_carries_no_signature() -> None:
    assert provenance_of(disk_with_info()).sides[0].signature is None


def test_a_short_run_of_text_is_not_a_signature() -> None:
    assert provenance_of(disk_with_info(x20=b"ab")).sides[0].signature is None


def test_an_unformatted_side_carries_no_signature() -> None:
    blank, _ = decode(blank_image(sides=1, headered=False, formatted=False))

    assert provenance_of(blank).sides[0].signature is None
