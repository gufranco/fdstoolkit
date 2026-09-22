from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from fdstoolkit.codecs.fds import SIDE_SIZE, decode
from fdstoolkit.fdskey.card import (
    BACKUP_SUFFIX,
    EVERDRIVE_SAVE_NAME,
    FirmwareVariant,
    backup_name,
    card_blank,
    everdrive_save_path,
    firmware_checksum,
)
from fdstoolkit.fdskey.lint import lint_card_image


def test_a_checksum_file_holds_the_md5_as_hex_text() -> None:
    firmware = bytes(range(64))

    text = firmware_checksum(firmware)

    assert text == hashlib.md5(firmware, usedforsecurity=False).hexdigest()
    assert len(text) == 32


def test_a_checksum_is_lowercase_so_two_runs_agree() -> None:
    assert firmware_checksum(b"abc") == firmware_checksum(b"abc").lower()


def test_the_everdrive_save_path_follows_the_card_layout() -> None:
    assert everdrive_save_path("Game.fds") == f"EDN8/gamedata/Game.fds/{EVERDRIVE_SAVE_NAME}"


def test_the_everdrive_save_path_keeps_the_extension() -> None:
    assert everdrive_save_path("Game") == f"EDN8/gamedata/Game.fds/{EVERDRIVE_SAVE_NAME}"


def test_a_backup_name_appends_the_documented_suffix() -> None:
    assert backup_name("Game.fds") == f"Game.fds{BACKUP_SUFFIX}"


def test_a_blank_for_released_firmware_is_all_zeros() -> None:
    data = card_blank(sides=1, variant=FirmwareVariant.RELEASED)

    assert data == bytes(SIDE_SIZE)


def test_a_blank_for_the_master_build_carries_a_disk_info_block() -> None:
    data = card_blank(sides=1, variant=FirmwareVariant.MASTER)

    disk, _ = decode(data)

    assert disk.sides[0].is_formatted
    assert lint_card_image(data, name=Path("blank.fds")) == ()


def test_a_blank_is_headerless_because_the_firmware_ignores_a_header() -> None:
    assert len(card_blank(sides=2, variant=FirmwareVariant.MASTER)) == 2 * SIDE_SIZE


def test_a_blank_can_carry_up_to_eight_sides() -> None:
    assert len(card_blank(sides=8, variant=FirmwareVariant.RELEASED)) == 8 * SIDE_SIZE


def test_a_blank_beyond_eight_sides_is_refused() -> None:
    with pytest.raises(ValueError, match="between 1 and 8"):
        card_blank(sides=9, variant=FirmwareVariant.RELEASED)


def test_two_blanks_of_the_same_shape_are_identical() -> None:
    assert card_blank(sides=3, variant=FirmwareVariant.MASTER) == card_blank(
        sides=3,
        variant=FirmwareVariant.MASTER,
    )
