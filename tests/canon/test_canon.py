from __future__ import annotations

import hashlib

import pytest

from fdstk.codecs.fds import SIDE_SIZE, decode
from fdstk.codecs.qd import decode as decode_qd
from fdstk.codecs.qd import encode as encode_qd
from fdstk.core.canon import (
    CANON_VERSION,
    canonicalise,
    digest_string,
    parse_digest_string,
    profile_by_name,
    restore,
)
from fdstk.core.diskinfo import CONTENT_PROFILE, DATA_PROFILE, RAW_PROFILE


def disk_info(*, rewrite_count: int = 0, serial: int = 0, name: bytes = b"SMB") -> bytes:
    payload = bytearray(56)
    payload[0] = 0x01
    payload[1:15] = b"*NINTENDO-HVC*"
    payload[0x10:0x13] = name
    payload[0x1F:0x22] = bytes([0x61, 0x02, 0x15])
    payload[0x22] = 0x49
    payload[0x2C:0x2F] = bytes([0x63, 0x08, 0x01])
    payload[0x31:0x33] = serial.to_bytes(2, "little")
    payload[0x34] = rewrite_count
    return bytes(payload)


def side_bytes(
    *,
    rewrite_count: int = 0,
    serial: int = 0,
    name: bytes = b"SMB",
    tail: bytes = b"",
) -> bytes:
    out = bytearray(disk_info(rewrite_count=rewrite_count, serial=serial, name=name))
    out += bytes([0x02, 0x01])
    out += (
        bytes([0x03, 0x00, 0x00])
        + b"FILE    "
        + (0x6000).to_bytes(2, "little")
        + (4).to_bytes(2, "little")
        + bytes([0x00])
    )
    out += bytes([0x04]) + bytes([0xAA]) * 4
    out += tail
    return bytes(out).ljust(SIDE_SIZE, b"\0")


def test_raw_profile_returns_the_image_unchanged() -> None:
    original = side_bytes(rewrite_count=3, serial=0x1234)
    disk, _ = decode(original)

    result = canonicalise(disk, RAW_PROFILE)

    assert result.data == original


def test_content_profile_makes_two_physical_disks_agree() -> None:
    factory, _ = decode(side_bytes())
    kiosk, _ = decode(side_bytes(rewrite_count=3, serial=0x1234))

    assert canonicalise(factory, CONTENT_PROFILE).data == canonicalise(kiosk, CONTENT_PROFILE).data


def test_content_profile_keeps_two_different_games_apart() -> None:
    one, _ = decode(side_bytes())
    other, _ = decode(side_bytes(name=b"ZEL"))

    assert canonicalise(one, CONTENT_PROFILE).data != canonicalise(other, CONTENT_PROFILE).data


def test_content_profile_zeroes_data_left_after_the_last_block() -> None:
    clean, _ = decode(side_bytes())
    stale, _ = decode(side_bytes(tail=bytes([0xDE, 0xAD, 0xBE, 0xEF])))

    assert canonicalise(clean, CONTENT_PROFILE).data == canonicalise(stale, CONTENT_PROFILE).data


def test_content_profile_drops_the_crc_so_a_qd_and_an_fds_agree() -> None:
    from_fds, _ = decode(side_bytes())
    as_qd, _ = encode_qd(from_fds)
    from_qd, _ = decode_qd(as_qd)

    canonical_fds = canonicalise(from_fds, CONTENT_PROFILE).data
    canonical_qd = canonicalise(from_qd, CONTENT_PROFILE).data

    assert canonical_fds == canonical_qd


def test_data_profile_ignores_the_whole_disk_label() -> None:
    one, _ = decode(side_bytes(name=b"SMB"))
    other, _ = decode(side_bytes(name=b"ZEL"))

    assert canonicalise(one, DATA_PROFILE).data == canonicalise(other, DATA_PROFILE).data


def test_every_canonical_side_has_the_nominal_length() -> None:
    disk, _ = decode(side_bytes() * 2)

    result = canonicalise(disk, CONTENT_PROFILE)

    assert len(result.data) == 2 * SIDE_SIZE


def test_canonicalisation_is_idempotent() -> None:
    disk, _ = decode(side_bytes(rewrite_count=3, tail=bytes([0x01])))

    once = canonicalise(disk, CONTENT_PROFILE)
    twice = canonicalise(decode(once.data)[0], CONTENT_PROFILE)

    assert once.data == twice.data


def test_the_digest_is_the_sha256_of_the_canonical_bytes() -> None:
    disk, _ = decode(side_bytes())

    result = canonicalise(disk, CONTENT_PROFILE)

    assert result.sha256 == hashlib.sha256(result.data).hexdigest()


def test_the_digest_string_names_its_version_and_profile() -> None:
    disk, _ = decode(side_bytes())

    text = digest_string(canonicalise(disk, CONTENT_PROFILE))

    assert text.startswith(f"fdscanon:v{CANON_VERSION}:content/v1:")
    assert parse_digest_string(text).profile == "content/v1"


def test_a_digest_string_that_is_not_one_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a canonical digest"):
        parse_digest_string("sha256:abc")


def test_the_sidecar_restores_the_original_bytes_exactly() -> None:
    original = side_bytes(rewrite_count=3, serial=0x1234, tail=bytes([0xDE, 0xAD]))
    disk, _ = decode(original)

    result = canonicalise(disk, CONTENT_PROFILE)

    assert restore(result) == original


def test_the_sidecar_restores_an_image_that_carried_crcs() -> None:
    disk, _ = decode(side_bytes())
    original, _ = encode_qd(disk)
    from_qd, _ = decode_qd(original)

    result = canonicalise(from_qd, CONTENT_PROFILE)

    assert restore(result) == original


def test_the_sidecar_restores_a_headered_image() -> None:
    original = b"FDS\x1a" + bytes([1]) + bytes(11) + side_bytes()
    disk, _ = decode(original)

    result = canonicalise(disk, CONTENT_PROFILE)

    assert restore(result) == original


def test_restore_of_a_raw_result_returns_the_same_bytes() -> None:
    original = side_bytes()
    disk, _ = decode(original)

    assert restore(canonicalise(disk, RAW_PROFILE)) == original


def test_a_raw_result_keeps_the_crcs_of_a_qd_image() -> None:
    disk, _ = decode(side_bytes())
    original, _ = encode_qd(disk)
    from_qd, _ = decode_qd(original)

    assert canonicalise(from_qd, RAW_PROFILE).data == original


def test_a_profile_can_be_looked_up_by_name() -> None:
    assert profile_by_name("content") is CONTENT_PROFILE


def test_an_unknown_profile_name_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown profile"):
        profile_by_name("nope")


def test_a_digest_string_with_a_bad_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a canonical digest"):
        parse_digest_string("fdscanon:vX:content/v1:abc")


def test_a_canonical_side_longer_than_the_nominal_size_is_kept_whole() -> None:
    disk, _ = decode(side_bytes())
    side = disk.sides[0]
    stuffed = side.__class__(
        blocks=side.blocks,
        tail=bytes([0x01]) * SIDE_SIZE,
        capacity=SIDE_SIZE,
    )

    result = canonicalise(disk.__class__(sides=(stuffed,)), RAW_PROFILE)

    assert len(result.data) > SIDE_SIZE
