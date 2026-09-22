from __future__ import annotations

from pathlib import Path

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import SIDE_SIZE
from fdstoolkit.fdskey.lint import CARD_FILE_SUFFIX, FIRMWARE_BUFFER, lint_card_image


def formatted(sides: int = 1) -> bytes:
    return blank_image(sides=sides, headered=False, formatted=True, game_name="SMB")


def codes(findings: object) -> list[str]:
    return [finding.code for finding in findings]  # type: ignore[attr-defined]


def test_a_plain_headerless_image_passes() -> None:
    findings = lint_card_image(formatted(), name=Path("game.fds"))

    assert codes(findings) == []


def test_a_headered_image_passes_because_the_firmware_skips_the_header() -> None:
    headered = blank_image(sides=1, headered=True, formatted=True, game_name="SMB")

    assert codes(lint_card_image(headered, name=Path("game.fds"))) == []


def test_a_size_that_is_neither_multiple_nor_offset_is_rejected() -> None:
    assert "FK001" in codes(lint_card_image(formatted() + bytes(5), name=Path("game.fds")))


def test_an_all_zero_image_is_rejected_by_the_current_firmware() -> None:
    findings = lint_card_image(bytes(SIDE_SIZE), name=Path("blank.fds"))

    assert "FK002" in codes(findings)


def test_a_missing_verification_string_is_rejected() -> None:
    raw = bytearray(formatted())
    raw[1:15] = b"*NOT-NINTENDO*"

    assert "FK003" in codes(lint_card_image(bytes(raw), name=Path("game.fds")))


def test_a_stray_block_code_after_the_last_block_is_reported() -> None:
    raw = bytearray(formatted())
    raw[58] = 0x04

    assert "FK004" in codes(lint_card_image(bytes(raw), name=Path("game.fds")))


def test_an_image_that_overflows_the_emulation_buffer_is_rejected() -> None:
    raw = bytearray(formatted())
    raw[56:58] = bytes([0x02, 0x01])
    position = 58
    for index in range(48):
        header = (
            bytes([0x03, index, index])
            + b"FILE    "
            + (0x6000).to_bytes(2, "little")
            + (1300).to_bytes(2, "little")
            + bytes([0x00])
        )
        raw[position : position + len(header)] = header
        position += len(header)
        raw[position : position + 1 + 1300] = bytes([0x04]) + bytes(1300)
        position += 1 + 1300

    findings = lint_card_image(bytes(raw), name=Path("many.fds"))

    assert "FK005" in codes(findings)
    overflow = next(finding for finding in findings if finding.code == "FK005")
    assert overflow.detail["budget"] == FIRMWARE_BUFFER


def test_a_file_too_large_for_the_copy_program_is_reported() -> None:
    raw = bytearray(formatted())
    raw[56:58] = bytes([0x02, 0x01])
    header = (
        bytes([0x03, 0x00, 0x00])
        + b"HUGE    "
        + (0x6000).to_bytes(2, "little")
        + (40000).to_bytes(2, "little")
        + bytes([0x00])
    )
    raw[58 : 58 + len(header)] = header
    raw[74 : 74 + 1 + 40000] = bytes([0x04]) + bytes(40000)

    assert "FK006" in codes(lint_card_image(bytes(raw), name=Path("huge.fds")))


def test_a_non_ascii_filename_is_rejected() -> None:
    findings = lint_card_image(formatted(), name=Path("jogo-ação.fds"))

    assert "FK007" in codes(findings)


def test_a_wrong_extension_is_rejected() -> None:
    findings = lint_card_image(formatted(), name=Path("game.bin"))

    assert "FK008" in codes(findings)
    assert CARD_FILE_SUFFIX == ".fds"


def test_more_than_eight_sides_is_rejected() -> None:
    raw = blank_image(sides=8, headered=False, formatted=True) + formatted()

    assert "FK009" in codes(lint_card_image(raw, name=Path("big.fds")))


def test_every_finding_explains_itself() -> None:
    findings = lint_card_image(bytes(SIDE_SIZE), name=Path("blank.bin"))

    assert all(finding.message for finding in findings)
    assert all(finding.code.startswith("FK") for finding in findings)
