from __future__ import annotations

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.identify.integrity import (
    ILLEGAL_OPCODES,
    Suspicion,
    code_sanity,
    inspect_disk,
)


def _info() -> Block:
    payload = bytearray(56)
    payload[0x00] = BlockKind.DISK_INFO
    payload[0x01:0x0F] = b"*NINTENDO-HVC*"
    return Block(kind=BlockKind.DISK_INFO, payload=bytes(payload))


def _header(*, size: int, kind: int = 0, address: int = 0x6000) -> Block:
    payload = bytearray(16)
    payload[0x00] = BlockKind.FILE_HEADER
    payload[0x03:0x0B] = b"PRG     "
    payload[0x0B:0x0D] = address.to_bytes(2, "little")
    payload[0x0D:0x0F] = size.to_bytes(2, "little")
    payload[0x0F] = kind
    return Block(kind=BlockKind.FILE_HEADER, payload=bytes(payload))


def _data(body: bytes) -> Block:
    return Block(kind=BlockKind.FILE_DATA, payload=bytes([4]) + body)


def _disk(blocks: tuple[Block, ...], *, crc: bool = True) -> Disk:
    prepared = tuple(block.with_computed_crc() for block in blocks) if crc else blocks
    return Disk(sides=(Side(blocks=prepared, tail=b"", capacity=65500),))


CLEAN_CODE = bytes((0xA9, 0x00, 0x85, 0x10, 0x60)) * 40
ILLEGAL_CODE = bytes((0x02, 0x12, 0x22, 0x32, 0x42)) * 40


def test_clean_code_passes_the_opcode_check() -> None:
    report = code_sanity(CLEAN_CODE)

    assert report.illegal == 0
    assert report.plausible


def test_a_body_full_of_illegal_opcodes_is_implausible() -> None:
    report = code_sanity(ILLEGAL_CODE)

    assert report.illegal > 0
    assert not report.plausible


def test_an_empty_body_is_not_judged() -> None:
    report = code_sanity(b"")

    assert report.plausible
    assert report.illegal == 0


def test_every_illegal_opcode_is_a_known_byte() -> None:
    assert 0x02 in ILLEGAL_OPCODES
    assert 0xA9 not in ILLEGAL_OPCODES


def test_a_clean_image_raises_no_suspicion() -> None:
    disk = _disk((_info(), _header(size=len(CLEAN_CODE)), _data(CLEAN_CODE)))

    assert not inspect_disk(disk).suspicions


def test_a_program_file_of_nonsense_is_suspicious() -> None:
    disk = _disk((_info(), _header(size=len(ILLEGAL_CODE)), _data(ILLEGAL_CODE)))

    report = inspect_disk(disk)

    assert Suspicion.IMPLAUSIBLE_CODE in {item.kind for item in report.suspicions}


def test_a_character_file_is_not_checked_for_code() -> None:
    disk = _disk((_info(), _header(size=len(ILLEGAL_CODE), kind=1), _data(ILLEGAL_CODE)))

    assert not inspect_disk(disk).suspicions


def test_a_file_shorter_than_its_header_declares_is_suspicious() -> None:
    disk = _disk((_info(), _header(size=500), _data(CLEAN_CODE)))

    report = inspect_disk(disk)

    assert Suspicion.SIZE_MISMATCH in {item.kind for item in report.suspicions}


def test_every_crc_recomputing_cleanly_on_a_stripped_image_is_suspicious() -> None:
    disk = _disk((_info(), _header(size=len(CLEAN_CODE)), _data(CLEAN_CODE)))
    regenerated = Disk(
        sides=(
            Side(
                blocks=tuple(block.with_computed_crc() for block in disk.sides[0].blocks),
                tail=b"",
                capacity=65500,
            ),
        )
    )

    report = inspect_disk(regenerated, expect_original_crcs=True)

    assert Suspicion.REGENERATED_CRCS in {item.kind for item in report.suspicions}


def test_an_image_without_stored_crcs_is_not_accused_of_regenerating_them() -> None:
    disk = _disk((_info(), _header(size=len(CLEAN_CODE)), _data(CLEAN_CODE)), crc=False)

    report = inspect_disk(disk, expect_original_crcs=True)

    assert Suspicion.REGENERATED_CRCS not in {item.kind for item in report.suspicions}


def test_a_suspicion_names_where_it_was_found() -> None:
    disk = _disk((_info(), _header(size=len(ILLEGAL_CODE)), _data(ILLEGAL_CODE)))

    found = inspect_disk(disk).suspicions[0]

    assert found.side == 0
    assert found.detail


def test_a_report_says_whether_the_image_looks_sound() -> None:
    clean = _disk((_info(), _header(size=len(CLEAN_CODE)), _data(CLEAN_CODE)))

    assert inspect_disk(clean).sound
    assert not inspect_disk(
        _disk((_info(), _header(size=len(ILLEGAL_CODE)), _data(ILLEGAL_CODE)))
    ).sound
