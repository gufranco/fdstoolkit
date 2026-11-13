from __future__ import annotations

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import (
    CALIBRATION_GAME,
    FACTORY_P95_SIDE,
    FILES_PER_SIDE,
    LARGEST_FACTORY_SIDE,
    SIDE_PAYLOAD,
    TRUSTED_DRIVE,
    Pattern,
    calibration_disk,
    calibration_image,
    matching_side,
    pattern_of,
)
from fdstoolkit.codecs import fds
from fdstoolkit.codecs.raw import (
    class_histogram,
    decode_raw03,
    encode_block_stream,
    encode_era_b,
    unpack_raw03,
)
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.crc import block_crc, encode_crc
from fdstoolkit.drive.align import good_block

SYNC = bytes([0x80])
DOMINANT = 0.99
TRAILING_GAP = 4000


def shares(payload: bytes) -> tuple[float, float, float]:
    framed = SYNC + payload + encode_crc(block_crc(payload))
    counts = class_histogram(encode_era_b(framed))
    total = counts[0] + counts[1] + counts[2]
    return counts[0] / total, counts[1] / total, counts[2] / total


def test_every_side_reads_back_clean_through_the_drive_encoding() -> None:
    # Arrange
    disk = calibration_disk()

    # Act
    reads = [
        decode_raw03(
            unpack_raw03(encode_block_stream([block.payload for block in side.blocks]))
            + bytes(TRAILING_GAP)
        )[0]
        for side in disk.sides
    ]

    # Assert
    assert disk.side_count == 2
    assert [len(read.blocks) for read in reads] == [2 + 2 * FILES_PER_SIDE] * 2
    assert all(good_block(block) for read in reads for block in read.blocks)
    assert [[block.payload for block in read.blocks] for read in reads] == [
        [block.payload for block in side.blocks] for side in disk.sides
    ]


def test_a_read_block_that_failed_its_checksum_does_not_count() -> None:
    # Arrange
    side = calibration_disk().sides[0]
    stream = bytearray(unpack_raw03(encode_block_stream([b.payload for b in side.blocks])))
    read, _ = decode_raw03(bytes(stream) + bytes(TRAILING_GAP))
    info = read.blocks[0]

    # Act
    broken = Block(kind=info.kind, payload=info.payload, stored_crc=(info.computed_crc or 0) ^ 1)

    # Assert
    assert matching_side([broken, *read.blocks[1:]]) is None


def test_every_side_stays_under_what_factory_disks_carry() -> None:
    # Arrange
    disk = calibration_disk()

    # Act
    used = [sum(len(block.payload) for block in side.blocks) for side in disk.sides]

    # Assert
    assert used == [SIDE_PAYLOAD, SIDE_PAYLOAD]
    assert SIDE_PAYLOAD == 53_854
    assert SIDE_PAYLOAD < FACTORY_P95_SIDE < LARGEST_FACTORY_SIDE


def test_each_pattern_puts_the_intended_pulse_class_on_the_disk() -> None:
    # Arrange
    side = calibration_disk().sides[0]
    data = [block.payload for block in side.blocks if block.kind is BlockKind.FILE_DATA]

    # Act
    by_pattern = {pattern_of(payload): shares(payload) for payload in data}

    # Assert
    assert by_pattern[Pattern.LONG][2] >= DOMINANT
    assert by_pattern[Pattern.MEDIUM][1] >= DOMINANT
    assert all(share > 0.1 for share in by_pattern[Pattern.MIXED])


def test_the_image_is_the_same_every_time_and_decodes_back() -> None:
    # Arrange
    first = calibration_image(headered=False)

    # Act
    second = calibration_image(headered=False)

    # Assert
    assert first == second
    disk, _ = fds.decode(first)
    assert disk == calibration_disk()


def test_each_side_names_its_own_side_in_the_disk_info() -> None:
    # Arrange
    sides = 2

    # Act
    disk = calibration_disk(sides)

    # Assert
    assert disk.sides[0].blocks[0].payload != disk.sides[1].blocks[0].payload
    assert CALIBRATION_GAME.encode("ascii") in disk.sides[0].blocks[0].payload


def test_a_read_of_either_side_is_recognised() -> None:
    # Arrange
    disk = calibration_disk()

    # Act
    matched = [matching_side(side.blocks) for side in disk.sides]

    # Assert
    assert matched == list(disk.sides)


def test_a_read_that_kept_only_the_disk_info_and_one_header_is_recognised() -> None:
    # Arrange
    side = calibration_disk().sides[1]

    # Act
    matched = matching_side([side.blocks[0], side.blocks[4]])

    # Assert
    assert matched == side


def test_a_blank_formatted_with_the_same_game_code_is_not_a_calibration_disk() -> None:
    # Arrange
    data = blank_image(sides=1, headered=False, formatted=True, game_name=CALIBRATION_GAME)

    # Act
    blank, _ = fds.decode(data)

    # Assert
    assert matching_side(blank.sides[0].blocks) is None


def test_a_read_with_no_blocks_is_not_recognised() -> None:
    # Arrange
    blocks: list[Block] = []

    # Act
    result = matching_side(blocks)

    # Assert
    assert result is None


def test_the_trusted_drive_checklist_names_every_adjustment() -> None:
    # Arrange
    needles = ("clean", "hub", "35.5 mm", "factory disks", "speed test", "second drive")

    # Act
    text = " ".join(TRUSTED_DRIVE).lower()

    # Assert
    assert [needle for needle in needles if needle not in text] == []
