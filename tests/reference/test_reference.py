from __future__ import annotations

import pytest

from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.diskinfo import CONTENT_PROFILE, RELEASE_PROFILE
from fdstoolkit.master.corpus import build_masters, key_of
from fdstoolkit.master.reference import (
    SCHEMA,
    ReferenceSet,
    Verdict,
    reference_from,
)


def _payload(*, code: bytes = b"ABC", serial: int = 0xFFFF, tail_byte: int = 0) -> bytes:
    payload = bytearray(56)
    payload[0x00] = BlockKind.DISK_INFO
    payload[0x01:0x0F] = b"*NINTENDO-HVC*"
    payload[0x10:0x13] = code
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
    data = Block(kind=BlockKind.FILE_DATA, payload=bytes([4, byte])).with_computed_crc()
    return Disk(sides=(Side(blocks=(info, data), tail=b"", capacity=65500),))


def _set() -> ReferenceSet:
    report = build_masters([("a", _disk()), ("b", _disk(serial=0x1234))])
    return reference_from(report, version="2026-09-22")


def test_a_reference_set_carries_one_entry_per_group() -> None:
    reference = _set()

    assert len(reference.entries) == 1
    assert reference.entries[0].game_code == "ABC"
    assert reference.entries[0].dumps == 2
    assert reference.entries[0].agreement == 1.0
    assert reference.entries[0].names == ("a", "b")


def test_an_entry_rebuilds_the_key_it_came_from() -> None:
    assert _set().entries[0].key == key_of(_disk())


def test_a_matching_image_verifies() -> None:
    match = _set().verify(_disk())

    assert match.verdict is Verdict.MATCH
    assert match.matched
    assert match.entry is not None


def test_an_image_of_a_known_game_with_other_content_mismatches() -> None:
    match = _set().verify(_with_data(7))

    assert match.verdict is Verdict.MISMATCH
    assert match.entry is not None
    assert not match.matched


def test_an_image_of_an_unknown_game_is_unknown() -> None:
    match = _set().verify(_disk(code=b"ZZZ"))

    assert match.verdict is Verdict.UNKNOWN
    assert match.entry is None


def test_a_set_round_trips_through_json() -> None:
    reference = _set()

    restored = ReferenceSet.from_json(reference.to_json())

    assert restored.version == reference.version
    assert restored.profile is reference.profile
    assert restored.entries == reference.entries


def test_the_json_names_its_schema() -> None:
    assert SCHEMA in _set().to_json()


def test_a_document_of_another_schema_is_refused() -> None:
    with pytest.raises(ValueError, match=r"not a .* document"):
        ReferenceSet.from_json('{"schema": "other", "version": "1", "entries": []}')


def test_a_document_naming_an_unknown_profile_is_refused() -> None:
    text = f'{{"schema": "{SCHEMA}", "version": "1", "profile": "nope", "entries": []}}'

    with pytest.raises(ValueError, match="unknown profile"):
        ReferenceSet.from_json(text)


def test_a_set_finds_an_entry_by_its_digest() -> None:
    reference = _set()

    assert reference.by_digest(reference.entries[0].digest) is reference.entries[0]
    assert reference.by_digest("fdstoolkit:v1:release/v1:00") is None


def test_a_set_built_from_another_profile_keeps_it() -> None:
    report = build_masters([("a", _disk())], profile=CONTENT_PROFILE)

    reference = reference_from(report, version="1")

    assert reference.profile is CONTENT_PROFILE
    assert ReferenceSet.from_json(reference.to_json()).profile is CONTENT_PROFILE


def test_the_default_profile_is_release() -> None:
    assert _set().profile is RELEASE_PROFILE
