from __future__ import annotations

import pytest

from fdstoolkit.core.blocks import Block, BlockKind, CrcStatus
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.master.splice import splice

GOOD_TAIL = bytes(41)
BAD_TAIL = bytes([0x99]) + bytes(40)


def _payload(tail: bytes) -> bytes:
    return bytes([BlockKind.DISK_INFO]) + b"*NINTENDO-HVC*" + tail


def _disk(*, tail: bytes = GOOD_TAIL, valid: bool = True) -> Disk:
    payload = _payload(tail)
    block = (
        Block(kind=BlockKind.DISK_INFO, payload=payload).with_computed_crc()
        if valid
        else Block(kind=BlockKind.DISK_INFO, payload=payload, stored_crc=0x1234)
    )
    return Disk(sides=(Side(blocks=(block,), tail=b"", capacity=65500),))


def test_a_disk_with_no_bad_block_is_returned_unchanged() -> None:
    # Arrange
    primary = _disk()

    # Act
    result = splice(primary, [_disk()])

    # Assert
    assert not result.splices
    assert result.disk.sides[0].blocks[0].payload == primary.sides[0].blocks[0].payload


def test_a_bad_block_is_repaired_from_a_donor() -> None:
    # Arrange
    primary = _disk(tail=BAD_TAIL, valid=False)
    donors = [_disk()]

    # Act
    result = splice(primary, donors)

    # Assert
    assert len(result.splices) == 1
    assert result.disk.sides[0].blocks[0].payload == _payload(GOOD_TAIL)
    assert result.disk.sides[0].blocks[0].crc_status is CrcStatus.VALID


def test_a_splice_names_where_the_replacement_came_from() -> None:
    # Arrange
    primary = _disk(valid=False)
    donors = [_disk(valid=False), _disk()]

    # Act
    result = splice(primary, donors)

    # Assert
    assert result.splices[0].donor == 1
    assert result.splices[0].side == 0
    assert result.splices[0].block == 0
    assert result.splices[0].kind == "disk_info"


def test_a_bad_block_with_no_good_donor_stays_unrepaired() -> None:
    # Arrange
    primary = _disk(valid=False)
    donors = [_disk(valid=False)]

    # Act
    result = splice(primary, donors)

    # Assert
    assert not result.splices
    assert result.unrepaired == ((0, 0),)


def test_a_repaired_disk_reports_itself_complete() -> None:
    # Arrange
    primary = _disk(valid=False)
    donors = [_disk()]

    # Act
    result = splice(primary, donors)

    # Assert
    assert result.complete
    assert not result.unrepaired


def test_an_unrepaired_disk_reports_itself_incomplete() -> None:
    # Arrange
    primary, donor = _disk(valid=False), _disk(valid=False)

    # Act
    result = splice(primary, [donor])

    # Assert
    assert not result.complete


def test_splicing_without_a_donor_is_refused() -> None:
    # Arrange
    primary = _disk()
    donors: list[Disk] = []

    # Act
    with pytest.raises(ValueError, match="at least one donor") as raised:
        splice(primary, donors)

    # Assert
    assert raised.type is ValueError


def test_a_donor_of_another_shape_is_refused() -> None:
    # Arrange
    two = Disk(sides=(_disk().sides[0], _disk().sides[0]))

    # Act
    with pytest.raises(ValueError, match="different shape") as raised:
        splice(_disk(), [two])

    # Assert
    assert raised.type is ValueError


def test_a_donor_without_a_stored_crc_is_not_trusted() -> None:
    # Arrange
    stripped = Disk(
        sides=(
            Side(
                blocks=(Block(kind=BlockKind.DISK_INFO, payload=_payload(GOOD_TAIL)),),
                tail=b"",
                capacity=65500,
            ),
        )
    )

    # Act
    result = splice(_disk(valid=False), [stripped])

    # Assert
    assert not result.splices


def test_the_first_good_donor_wins() -> None:
    # Arrange
    other_good = _disk(tail=bytes([0x11]) + bytes(40))

    # Act
    result = splice(_disk(valid=False), [other_good, _disk()])

    # Assert
    assert result.disk.sides[0].blocks[0].payload == _payload(bytes([0x11]) + bytes(40))


def _info(game: bytes) -> Block:
    payload = bytearray(_payload(GOOD_TAIL))
    payload[0x10:0x13] = game
    return Block(kind=BlockKind.DISK_INFO, payload=bytes(payload)).with_computed_crc()


def _with(info: Block, second: Block) -> Disk:
    return Disk(sides=(Side(blocks=(info, second), tail=b"", capacity=65500),))


def _amount(count: int) -> Block:
    payload = bytes([BlockKind.FILE_AMOUNT, count])
    return Block(kind=BlockKind.FILE_AMOUNT, payload=payload).with_computed_crc()


def test_a_donor_holding_another_disk_is_refused() -> None:
    # Arrange
    broken = Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([2, 1]), stored_crc=0x1234)
    primary = _with(_info(b"ABC"), broken)
    donor = _with(_info(b"XYZ"), _amount(1))

    # Act
    with pytest.raises(ValueError, match="donor 1 holds another disk") as raised:
        splice(primary, [donor])

    # Assert
    assert str(raised.value) == (
        "donor 1 holds another disk: its side 0 disk information differs from the "
        "image's, so none of its blocks belong here"
    )


def test_a_donor_block_of_another_kind_is_not_taken() -> None:
    # Arrange
    broken = Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([2, 1]), stored_crc=0x1234)
    header = Block(kind=BlockKind.FILE_HEADER, payload=bytes([3]) + bytes(15)).with_computed_crc()
    primary = _with(_info(b"ABC"), broken)

    # Act
    result = splice(primary, [_with(_info(b"ABC"), header)])

    # Assert
    assert result.unrepaired == ((0, 1),)


def test_a_side_without_disk_information_still_takes_a_donor_block() -> None:
    # Arrange
    broken = Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([2, 1]), stored_crc=0x1234)
    primary = Disk(sides=(Side(blocks=(broken,), tail=b"", capacity=65500),))
    donor = Disk(sides=(Side(blocks=(_amount(1),), tail=b"", capacity=65500),))

    # Act
    result = splice(primary, [donor])

    # Assert
    assert result.disk.sides[0].blocks == (_amount(1),)
