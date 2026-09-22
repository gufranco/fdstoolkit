from __future__ import annotations

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from fdstoolkit.codecs import fds, qd
from fdstoolkit.codecs.raw import RawEncoding, decode_raw03, encode_block_stream, unpack_raw03
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.canon import canonicalise, restore
from fdstoolkit.core.crc import block_crc, decode_crc, encode_crc
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.diskinfo import CONTENT_PROFILE, VERIFICATION_STRING
from fdstoolkit.patch.build import build_ips
from fdstoolkit.patch.formats import apply_ips

SETTINGS = settings(max_examples=60, suppress_health_check=[HealthCheck.too_slow], deadline=None)


def disk_info(game_name: bytes, rewrite_count: int) -> bytes:
    payload = bytearray(56)
    payload[0] = 0x01
    payload[1:15] = VERIFICATION_STRING
    payload[0x10:0x13] = game_name
    payload[0x34] = rewrite_count
    return bytes(payload)


def file_header(number: int, size: int) -> bytes:
    return (
        bytes([0x03, number, number])
        + f"F{number:07d}".encode("ascii")[:8]
        + (0x6000).to_bytes(2, "little")
        + size.to_bytes(2, "little")
        + bytes([0x00])
    )


@st.composite
def sides(draw: st.DrawFn, *, capacity: int = fds.SIDE_SIZE) -> Side:
    name = draw(st.binary(min_size=3, max_size=3))
    rewrite_count = draw(st.integers(min_value=0, max_value=9))
    payloads = draw(st.lists(st.binary(min_size=0, max_size=64), min_size=0, max_size=6))
    declared = draw(st.integers(min_value=0, max_value=len(payloads)))

    blocks: list[Block] = [
        Block(kind=BlockKind.DISK_INFO, payload=disk_info(name, rewrite_count)),
        Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([0x02, declared])),
    ]
    for index, payload in enumerate(payloads):
        blocks.append(Block(kind=BlockKind.FILE_HEADER, payload=file_header(index, len(payload))))
        blocks.append(Block(kind=BlockKind.FILE_DATA, payload=bytes([0x04]) + payload))

    return Side(blocks=tuple(blocks), tail=b"", capacity=capacity)


@st.composite
def disks(draw: st.DrawFn, *, capacity: int = fds.SIDE_SIZE) -> Disk:
    count = draw(st.integers(min_value=1, max_value=3))
    return Disk(sides=tuple(draw(sides(capacity=capacity)) for _ in range(count)))


@SETTINGS
@given(disks())
def test_an_fds_image_survives_a_round_trip(disk: Disk) -> None:
    data, _ = fds.encode(disk, headered=False)
    rebuilt, _ = fds.decode(data)
    again, _ = fds.encode(rebuilt, headered=False)

    assert again == data


@SETTINGS
@given(disks(capacity=qd.SIDE_SIZE))
def test_a_qd_image_survives_a_round_trip(disk: Disk) -> None:
    data, _ = qd.encode(disk)
    rebuilt, _ = qd.decode(data)
    again, _ = qd.encode(rebuilt)

    assert again == data


@SETTINGS
@given(disks())
def test_a_header_survives_a_round_trip(disk: Disk) -> None:
    data, _ = fds.encode(disk, headered=True)
    rebuilt, _ = fds.decode(data)
    again, _ = fds.encode(rebuilt, headered=True)

    assert again == data
    assert rebuilt.header_side_count == disk.side_count


@SETTINGS
@given(disks())
def test_canonicalisation_is_reversible(disk: Disk) -> None:
    data, _ = fds.encode(disk, headered=False)
    parsed, _ = fds.decode(data)

    result = canonicalise(parsed, CONTENT_PROFILE)

    assert restore(result) == data


@SETTINGS
@given(disks())
def test_canonicalisation_is_idempotent(disk: Disk) -> None:
    data, _ = fds.encode(disk, headered=False)
    parsed, _ = fds.decode(data)

    once = canonicalise(parsed, CONTENT_PROFILE)
    twice = canonicalise(fds.decode(once.data)[0], CONTENT_PROFILE)

    assert once.data == twice.data


@SETTINGS
@given(disks(), st.integers(min_value=0, max_value=9))
def test_the_rewrite_count_never_changes_the_content_digest(disk: Disk, count: int) -> None:
    original = canonicalise(disk, CONTENT_PROFILE).sha256

    rewritten = bytearray(disk.sides[0].blocks[0].payload)
    rewritten[0x34] = count
    blocks = (
        Block(kind=BlockKind.DISK_INFO, payload=bytes(rewritten)),
        *disk.sides[0].blocks[1:],
    )
    altered = Disk(
        sides=(
            Side(blocks=blocks, tail=b"", capacity=disk.sides[0].capacity),
            *disk.sides[1:],
        )
    )

    assert canonicalise(altered, CONTENT_PROFILE).sha256 == original


@SETTINGS
@given(sides())
def test_a_pulse_stream_decodes_back_to_its_blocks(side: Side) -> None:
    payloads = [block.payload for block in side.blocks]
    stream = encode_block_stream(payloads, encoding=RawEncoding.ERA_B)

    decoded, _ = decode_raw03(unpack_raw03(stream))

    assert [block.payload for block in decoded.blocks] == payloads


@SETTINGS
@given(st.binary(min_size=0, max_size=256))
def test_a_crc_round_trips_through_its_encoding(payload: bytes) -> None:
    assert decode_crc(encode_crc(block_crc(payload))) == block_crc(payload)


@SETTINGS
@given(st.binary(max_size=512), st.binary(max_size=512))
def test_an_ips_patch_turns_one_file_into_the_other(source: bytes, target: bytes) -> None:
    assert apply_ips(build_ips(source, target), source) == target
