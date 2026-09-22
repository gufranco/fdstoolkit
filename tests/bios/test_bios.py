from __future__ import annotations

from dataclasses import replace

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.bios import BIOS_ERRORS, BootVerdict, predict_boot
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk
from fdstoolkit.edit.files import FileSpec, insert_file

KYODAKU_ADDRESS = 0x2800


def formatted(*, boot_file: int = 0) -> Disk:
    raw = bytearray(blank_image(sides=1, headered=False, formatted=True, game_name="SMB"))
    raw[0x19] = boot_file
    disk, _ = decode(bytes(raw))
    return disk


def add(
    disk: Disk,
    *,
    name: str,
    kind: FileKind,
    address: int,
    file_id: int,
    size: int = 224,
) -> Disk:
    return insert_file(
        disk,
        side=0,
        spec=FileSpec(name=name, address=address, kind=kind, data=b"\x00" * size, file_id=file_id),
    )


def licensed(*, boot_file: int = 1) -> Disk:
    disk = add(
        formatted(boot_file=boot_file),
        name="KYODAKU-",
        kind=FileKind.NAMETABLE,
        address=KYODAKU_ADDRESS,
        file_id=0,
    )
    return add(disk, name="MAIN", kind=FileKind.PROGRAM, address=0x6000, file_id=1)


def test_every_documented_error_has_a_message() -> None:
    assert BIOS_ERRORS[0x20] == "approval check failed"
    assert BIOS_ERRORS[0x21] == "NINTENDO-HVC string mismatch"
    assert BIOS_ERRORS[0x27] == "block failed CRC"


def test_a_licensed_disk_boots() -> None:
    report = predict_boot(licensed())

    assert report.sides[0].verdict is BootVerdict.BOOTS
    assert report.sides[0].error is None


def test_boot_files_are_those_at_or_below_the_boot_code() -> None:
    report = predict_boot(licensed(boot_file=1))

    assert [entry.name for entry in report.sides[0].boot_files] == ["KYODAKU-", "MAIN"]


def test_a_file_above_the_boot_code_is_not_loaded_at_start_up() -> None:
    report = predict_boot(licensed(boot_file=0))

    assert [entry.name for entry in report.sides[0].boot_files] == ["KYODAKU-"]


def test_a_disk_with_no_approval_file_is_flagged_as_bypass_or_error_20() -> None:
    disk = add(
        formatted(boot_file=0), name="MAIN", kind=FileKind.PROGRAM, address=0x6000, file_id=0
    )

    side = predict_boot(disk).sides[0]

    assert side.verdict is BootVerdict.NEEDS_BYPASS
    assert side.error == 0x20


def test_an_approval_file_at_the_wrong_address_does_not_count() -> None:
    disk = add(
        formatted(boot_file=0),
        name="KYODAKU-",
        kind=FileKind.NAMETABLE,
        address=0x2900,
        file_id=0,
    )

    assert predict_boot(disk).sides[0].verdict is BootVerdict.NEEDS_BYPASS


def test_an_approval_file_that_is_not_a_boot_file_does_not_count() -> None:
    disk = add(
        formatted(boot_file=0),
        name="KYODAKU-",
        kind=FileKind.NAMETABLE,
        address=KYODAKU_ADDRESS,
        file_id=5,
    )

    assert predict_boot(disk).sides[0].verdict is BootVerdict.NEEDS_BYPASS


def test_a_program_file_named_kyodaku_does_not_count() -> None:
    disk = add(
        formatted(boot_file=0),
        name="KYODAKU-",
        kind=FileKind.PROGRAM,
        address=KYODAKU_ADDRESS,
        file_id=0,
    )

    assert predict_boot(disk).sides[0].verdict is BootVerdict.NEEDS_BYPASS


def test_an_altered_verification_string_is_error_21() -> None:
    disk = licensed()
    side = disk.sides[0]
    payload = bytearray(side.blocks[0].payload)
    payload[1:15] = b"*NOT-NINTENDO*"
    blocks = (replace(side.blocks[0], payload=bytes(payload)), *side.blocks[1:])
    altered = Disk(sides=(replace(side, blocks=blocks),))

    report = predict_boot(altered).sides[0]

    assert report.verdict is BootVerdict.FAILS
    assert report.error == 0x21


def test_an_unformatted_side_is_error_22() -> None:
    blank, _ = decode(blank_image(sides=1, headered=False, formatted=False))

    report = predict_boot(blank).sides[0]

    assert report.verdict is BootVerdict.FAILS
    assert report.error == 0x22


def test_a_side_with_no_boot_file_loads_nothing() -> None:
    report = predict_boot(formatted(boot_file=0)).sides[0]

    assert report.boot_files == ()
    assert report.verdict is BootVerdict.NEEDS_BYPASS


def test_the_message_names_the_error_code() -> None:
    disk = add(
        formatted(boot_file=0), name="MAIN", kind=FileKind.PROGRAM, address=0x6000, file_id=0
    )

    side = predict_boot(disk).sides[0]

    assert "20" in side.message
    assert "approval" in side.message


def test_every_side_is_reported() -> None:
    disk, _ = decode(blank_image(sides=2, headered=False, formatted=True))

    assert [side.side for side in predict_boot(disk).sides] == [0, 1]


def test_the_approval_file_is_recognised_by_what_it_loads_not_by_its_name() -> None:
    disk = add(
        formatted(boot_file=0),
        name="4Vx",
        kind=FileKind.NAMETABLE,
        address=KYODAKU_ADDRESS,
        file_id=0,
    )

    assert predict_boot(disk).sides[0].verdict is BootVerdict.BOOTS


def test_a_file_too_short_to_cover_the_approval_data_does_not_count() -> None:
    disk = add(
        formatted(boot_file=0),
        name="KYODAKU-",
        kind=FileKind.NAMETABLE,
        address=KYODAKU_ADDRESS,
        file_id=0,
        size=16,
    )

    assert predict_boot(disk).sides[0].verdict is BootVerdict.NEEDS_BYPASS


def test_a_larger_nametable_load_that_spans_the_approval_data_counts() -> None:
    disk = add(
        formatted(boot_file=0),
        name="SCREEN",
        kind=FileKind.NAMETABLE,
        address=0x2000,
        file_id=0,
        size=0x1000,
    )

    assert predict_boot(disk).sides[0].verdict is BootVerdict.BOOTS
