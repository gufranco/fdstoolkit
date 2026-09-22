from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final

from fdstk.core.blocks import BlockKind
from fdstk.core.crc import encode_crc
from fdstk.core.disk import Disk, Side
from fdstk.core.diskinfo import PROFILES, RAW_PROFILE, MaskProfile, mask_disk_info
from fdstk.core.parse import parse_side

CANON_VERSION: Final = 1
CANON_SIDE_SIZE: Final = 65500
DIGEST_PREFIX: Final = "fdscanon"
HEADER_MAGIC: Final = b"FDS\x1a"
HEADER_SIZE: Final = 16


@dataclass(frozen=True, slots=True)
class SideSidecar:
    capacity: int
    had_crc: bool
    stored_crcs: tuple[int | None, ...]
    tail: bytes
    disk_info: bytes | None


@dataclass(frozen=True, slots=True)
class Sidecar:
    header_side_count: int | None
    sides: tuple[SideSidecar, ...]


@dataclass(frozen=True, slots=True)
class CanonResult:
    data: bytes
    profile: MaskProfile
    sidecar: Sidecar

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()


@dataclass(frozen=True, slots=True)
class ParsedDigest:
    version: int
    profile: str
    sha256: str


def _side_sidecar(side: Side) -> SideSidecar:
    had_crc = any(block.stored_crc is not None for block in side.blocks)
    disk_info = side.blocks[0].payload if side.is_formatted else None
    return SideSidecar(
        capacity=side.capacity,
        had_crc=had_crc,
        stored_crcs=tuple(block.stored_crc for block in side.blocks),
        tail=side.tail,
        disk_info=disk_info,
    )


def _encode_raw_side(side: Side) -> bytes:
    had_crc = any(block.stored_crc is not None for block in side.blocks)
    out = bytearray()
    for block in side.blocks:
        out += block.payload
        if had_crc:
            out += encode_crc(block.stored_crc if block.stored_crc is not None else 0)
    out += side.tail
    if len(out) >= side.capacity:
        return bytes(out)
    return bytes(out).ljust(side.capacity, b"\0")


def _encode_canonical_side(side: Side, profile: MaskProfile) -> bytes:
    out = bytearray()
    for block in side.blocks:
        payload = block.payload
        if block.kind is BlockKind.DISK_INFO:
            payload = mask_disk_info(payload, profile)
        out += payload
    if len(out) >= CANON_SIDE_SIZE:
        return bytes(out)
    return bytes(out).ljust(CANON_SIDE_SIZE, b"\0")


def canonicalise(disk: Disk, profile: MaskProfile) -> CanonResult:
    sidecar = Sidecar(
        header_side_count=disk.header_side_count,
        sides=tuple(_side_sidecar(side) for side in disk.sides),
    )
    out = bytearray()
    if profile is RAW_PROFILE:
        if disk.header_side_count is not None:
            out += HEADER_MAGIC + bytes([disk.header_side_count])
            out += bytes(HEADER_SIZE - len(HEADER_MAGIC) - 1)
        for side in disk.sides:
            out += _encode_raw_side(side)
    else:
        for side in disk.sides:
            out += _encode_canonical_side(side, profile)
    return CanonResult(data=bytes(out), profile=profile, sidecar=sidecar)


def digest_string(result: CanonResult) -> str:
    return f"{DIGEST_PREFIX}:v{CANON_VERSION}:{result.profile.label}:{result.sha256}"


def parse_digest_string(text: str) -> ParsedDigest:
    parts = text.split(":")
    expected_parts = 4
    if len(parts) != expected_parts or parts[0] != DIGEST_PREFIX or not parts[1].startswith("v"):
        message = f"not a canonical digest: {text}"
        raise ValueError(message)
    try:
        version = int(parts[1][1:])
    except ValueError as error:
        message = f"not a canonical digest: {text}"
        raise ValueError(message) from error
    return ParsedDigest(version=version, profile=parts[2], sha256=parts[3])


def profile_by_name(name: str) -> MaskProfile:
    profile = PROFILES.get(name)
    if profile is None:
        known = ", ".join(sorted(PROFILES))
        message = f"unknown profile {name}, known profiles are {known}"
        raise ValueError(message)
    return profile


def _restore_side(data: bytes, sidecar: SideSidecar) -> bytes:
    side, _ = parse_side(data, has_crc=False, capacity=CANON_SIDE_SIZE)
    out = bytearray()
    for index, block in enumerate(side.blocks):
        payload = block.payload
        if block.kind is BlockKind.DISK_INFO and sidecar.disk_info is not None:
            payload = sidecar.disk_info
        out += payload
        if sidecar.had_crc:
            stored = sidecar.stored_crcs[index] if index < len(sidecar.stored_crcs) else None
            out += encode_crc(stored if stored is not None else 0)
    out += sidecar.tail
    if len(out) >= sidecar.capacity:
        return bytes(out)
    return bytes(out).ljust(sidecar.capacity, b"\0")


def restore(result: CanonResult) -> bytes:
    if result.profile is RAW_PROFILE:
        return result.data

    out = bytearray()
    if result.sidecar.header_side_count is not None:
        out += HEADER_MAGIC + bytes([result.sidecar.header_side_count])
        out += bytes(HEADER_SIZE - len(HEADER_MAGIC) - 1)
    for index, side_sidecar in enumerate(result.sidecar.sides):
        chunk = result.data[index * CANON_SIDE_SIZE : (index + 1) * CANON_SIDE_SIZE]
        out += _restore_side(chunk, side_sidecar)
    return bytes(out)
