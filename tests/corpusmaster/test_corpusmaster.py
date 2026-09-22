from __future__ import annotations

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.diskinfo import CONTENT_PROFILE
from fdstoolkit.master.corpus import UNKNOWN_CODE, build_masters, group_dumps, key_of


def _payload(
    *,
    code: bytes = b"ABC",
    version: int = 0,
    disk_number: int = 0,
    serial: int = 0xFFFF,
    tail_byte: int = 0,
) -> bytes:
    payload = bytearray(56)
    payload[0x00] = BlockKind.DISK_INFO
    payload[0x01:0x0F] = b"*NINTENDO-HVC*"
    payload[0x10:0x13] = code
    payload[0x14] = version
    payload[0x16] = disk_number
    payload[0x31:0x33] = serial.to_bytes(2, "little")
    payload[0x37] = tail_byte
    return bytes(payload)


def _disk(**kwargs: object) -> Disk:
    payload = _payload(**kwargs)  # type: ignore[arg-type]
    return Disk(
        sides=(
            Side(
                blocks=(Block(kind=BlockKind.DISK_INFO, payload=payload).with_computed_crc(),),
                tail=b"",
                capacity=65500,
            ),
        )
    )


def _with_data(byte: int) -> Disk:
    info = Block(kind=BlockKind.DISK_INFO, payload=_payload()).with_computed_crc()
    amount = Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([2, 1])).with_computed_crc()
    data = Block(kind=BlockKind.FILE_DATA, payload=bytes([4, byte, byte])).with_computed_crc()
    return Disk(
        sides=(Side(blocks=(info, amount, data), tail=b"", capacity=65500),),
    )


def test_a_disk_is_keyed_by_its_game_code_version_and_disk_number() -> None:
    key = key_of(_disk(code=b"XYZ", version=2, disk_number=1))

    assert key.game_code == "XYZ"
    assert key.version == 2
    assert key.disk_number == 1
    assert key.sides == 1
    assert "XYZ v2 disk 1" in key.label


def test_a_disk_with_no_side_falls_back_to_an_unknown_key() -> None:
    assert key_of(Disk(sides=())).game_code == UNKNOWN_CODE


def test_an_unformatted_side_falls_back_to_an_unknown_key() -> None:
    blank = Disk(sides=(Side(blocks=(), tail=b"", capacity=65500),))

    assert key_of(blank).game_code == UNKNOWN_CODE


def test_dumps_of_the_same_game_land_in_one_group() -> None:
    groups = group_dumps([("a", _disk()), ("b", _disk()), ("c", _disk(code=b"ZZZ"))])

    assert len(groups) == 2
    assert len(groups[key_of(_disk())]) == 2


def test_two_dumps_differing_only_in_the_writer_stamp_agree_on_release() -> None:
    report = build_masters([("a", _disk(serial=0xFFFF)), ("b", _disk(serial=0x1234))])

    assert len(report.groups) == 1
    assert report.groups[0].unanimous
    assert report.groups[0].agreement == 1.0
    assert report.agreement == 1.0


def test_two_dumps_differing_in_content_do_not_agree() -> None:
    report = build_masters([("a", _with_data(1)), ("b", _with_data(2))])

    assert report.groups[0].variants == 2
    assert not report.groups[0].unanimous
    assert report.groups[0].dissenters


def test_the_majority_reading_becomes_the_master() -> None:
    report = build_masters([("a", _with_data(1)), ("b", _with_data(1)), ("c", _with_data(2))])

    group = report.groups[0]
    assert group.agreement == 2 / 3
    assert group.dissenters == ("c",)


def test_a_group_of_matching_shapes_carries_a_block_consensus() -> None:
    report = build_masters([("a", _with_data(1)), ("b", _with_data(1))])

    assert report.groups[0].consensus is not None
    assert report.groups[0].consensus.stable


def test_a_lone_dump_has_no_block_consensus() -> None:
    report = build_masters([("a", _disk())])

    assert report.groups[0].consensus is None


def test_a_group_of_differing_shapes_has_no_block_consensus() -> None:
    report = build_masters([("a", _disk()), ("b", _with_data(1))])

    assert report.groups[0].consensus is None


def test_the_report_counts_every_dump_it_saw() -> None:
    report = build_masters([("a", _disk()), ("b", _disk()), ("c", _disk(code=b"ZZZ"))])

    assert report.dumps == 3
    assert len(report.contested) == 0


def test_an_empty_corpus_reports_nothing() -> None:
    report = build_masters([])

    assert report.groups == ()
    assert report.agreement == 0.0
    assert report.dumps == 0


def test_another_profile_can_be_asked_for() -> None:
    report = build_masters(
        [("a", _disk(serial=0xFFFF)), ("b", _disk(serial=0x1234))],
        profile=CONTENT_PROFILE,
    )

    assert report.profile is CONTENT_PROFILE
    assert report.groups[0].unanimous
