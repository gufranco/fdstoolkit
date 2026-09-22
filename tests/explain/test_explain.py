from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from fdstk.build.blank import blank_image
from fdstk.codecs.fds import decode
from fdstk.core.blocks import FileKind
from fdstk.core.disk import Disk
from fdstk.edit.diskinfo import apply_edits
from fdstk.edit.files import FileSpec, insert_file
from fdstk.quality.explain import FileChange, explain


def sample(*, sides: int = 1) -> Disk:
    disk, _ = decode(blank_image(sides=sides, headered=False, formatted=True, game_name="SMB"))
    return disk


def edited(disk: Disk, edits: Mapping[str, object], *, side: int = 0) -> Disk:
    changed, _ = apply_edits(disk, side=side, edits=edits)
    return changed


def with_file(disk: Disk, *, name: str = "MAIN", data: bytes = b"\x01\x02") -> Disk:
    return insert_file(
        disk,
        side=0,
        spec=FileSpec(name=name, address=0x6000, kind=FileKind.PROGRAM, data=data),
    )


def replace_info(disk: Disk, payload: bytes) -> Disk:
    side = disk.sides[0]
    blocks = (replace(side.blocks[0], payload=payload), *side.blocks[1:])
    return Disk(sides=(replace(side, blocks=blocks), *disk.sides[1:]))


def test_two_identical_images_explain_as_identical() -> None:
    result = explain(sample(), sample())

    assert result.identical
    assert result.headline == "identical"


def test_a_different_side_count_is_a_different_disk() -> None:
    result = explain(sample(sides=1), sample(sides=2))

    assert not result.same_software
    assert "1 side(s) against 2" in result.headline


def test_a_rewritten_disk_reads_as_the_same_software() -> None:
    other = edited(sample(), {"rewritten_date": "1988-02-13", "rewrite_count": 3})
    payload = bytearray(other.sides[0].blocks[0].payload)
    payload[0x31:0x33] = b"\x12\x34"

    result = explain(sample(), replace_info(other, bytes(payload)))

    assert result.same_software
    assert result.headline == (
        "same software, rewritten 1988-02-13, writer serial 0x1234, rewrite count 3"
    )


def test_a_different_game_name_is_different_software() -> None:
    result = explain(sample(), edited(sample(), {"game_name": "ZEL"}))

    assert not result.same_software
    assert result.headline == "different software"


def test_an_identity_field_difference_is_marked_as_one() -> None:
    result = explain(sample(), edited(sample(), {"game_version": 2}))

    difference = next(entry for entry in result.fields if entry.field == "game_version")
    assert difference.identity
    assert (difference.left, difference.right) == ("0x00", "0x02")


def test_a_provenance_field_difference_is_not_an_identity_one() -> None:
    result = explain(sample(), edited(sample(), {"actual_side": 1}))

    difference = next(entry for entry in result.fields if entry.field == "actual_side")
    assert not difference.identity
    assert result.headline == "same software, 1 provenance field(s) differ"


def test_an_unreadable_date_falls_back_to_hex() -> None:
    payload = bytearray(sample().sides[0].blocks[0].payload)
    payload[0x2C:0x2F] = b"\xff\xff\xff"

    result = explain(sample(), replace_info(sample(), bytes(payload)))

    difference = next(entry for entry in result.fields if entry.field == "rewritten_date")
    assert difference.right == "ffffff"


def test_the_verification_string_is_rendered_as_text() -> None:
    payload = bytearray(sample().sides[0].blocks[0].payload)
    payload[0x01:0x0F] = b"*NOT-NINTENDO*"

    result = explain(sample(), replace_info(sample(), bytes(payload)))

    difference = next(entry for entry in result.fields if entry.field == "verification")
    assert difference.right == "*NOT-NINTENDO*"


def test_a_multi_byte_unknown_field_is_rendered_as_hex() -> None:
    payload = bytearray(sample().sides[0].blocks[0].payload)
    payload[0x27:0x2C] = b"\x01\x02\x03\x04\x05"

    result = explain(sample(), replace_info(sample(), bytes(payload)))

    difference = next(entry for entry in result.fields if entry.field == "unknown_27")
    assert difference.right == "0102030405"


def test_an_unreadable_rewrite_count_falls_back_to_hex() -> None:
    payload = bytearray(sample().sides[0].blocks[0].payload)
    payload[0x34] = 0xFF

    result = explain(sample(), replace_info(sample(), bytes(payload)))

    difference = next(entry for entry in result.fields if entry.field == "rewrite_count")
    assert difference.right == "ff"


def test_an_added_file_is_reported() -> None:
    result = explain(sample(), with_file(sample()))

    assert [entry.change for entry in result.files] == [FileChange.ADDED]
    assert result.headline == "same software, 1 file(s) differ"


def test_a_removed_file_is_reported() -> None:
    result = explain(with_file(sample()), sample())

    assert [entry.change for entry in result.files] == [FileChange.REMOVED]


def test_changed_file_data_is_reported_with_both_sizes() -> None:
    result = explain(with_file(sample()), with_file(sample(), data=b"\x01\x02\x03"))

    entry = result.files[0]
    assert entry.change is FileChange.CHANGED
    assert entry.detail == "2 bytes against 3"


def test_a_renamed_file_is_reported_by_name() -> None:
    result = explain(with_file(sample()), with_file(sample(), name="BOOT"))

    assert result.files[0].detail == "named 'MAIN' against 'BOOT'"


def test_a_relocated_file_is_reported_by_address() -> None:
    right = insert_file(
        sample(),
        side=0,
        spec=FileSpec(name="MAIN", address=0x7000, kind=FileKind.PROGRAM, data=b"\x01\x02"),
    )

    result = explain(with_file(sample()), right)

    assert result.files[0].detail == "loads at 0x6000 against 0x7000"


def test_a_file_that_changed_kind_is_reported_by_kind() -> None:
    right = insert_file(
        sample(),
        side=0,
        spec=FileSpec(name="MAIN", address=0x6000, kind=FileKind.CHARACTER, data=b"\x01\x02"),
    )

    result = explain(with_file(sample()), right)

    assert result.files[0].detail == "program against character"


def test_an_unformatted_side_contributes_no_field_differences() -> None:
    blank, _ = decode(blank_image(sides=1, headered=False, formatted=False))

    result = explain(blank, sample())

    assert result.fields == ()


def test_an_unchanged_file_produces_no_difference() -> None:
    result = explain(with_file(sample()), with_file(sample()))

    assert result.files == ()
    assert result.identical


def test_an_unreadable_rewritten_date_stays_out_of_the_headline() -> None:
    payload = bytearray(sample().sides[0].blocks[0].payload)
    payload[0x2C:0x2F] = b"\xff\xff\xff"

    result = explain(sample(), replace_info(sample(), bytes(payload)))

    assert result.headline == "same software, 1 provenance field(s) differ"
