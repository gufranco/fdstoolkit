from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fdstoolkit.core.blocks import DISK_INFO_SIZE

VERIFICATION_STRING: Final = b"*NINTENDO-HVC*"
SHOWA_EPOCH: Final = 1925
MAX_BCD_DIGIT: Final = 9


@dataclass(frozen=True, slots=True)
class Field:
    name: str
    offset: int
    length: int
    description: str
    provenance: bool = False


DISK_INFO_FIELDS: Final[tuple[Field, ...]] = (
    Field("block_code", 0x00, 1, "block code, 0x01"),
    Field("verification", 0x01, 14, "disk verification string"),
    Field("licensee", 0x0F, 1, "licensee code"),
    Field("game_name", 0x10, 3, "three-letter game code"),
    Field("game_type", 0x13, 1, "normal, event, reduction"),
    Field("game_version", 0x14, 1, "game revision"),
    Field("side", 0x15, 1, "side number"),
    Field("disk_number", 0x16, 1, "disk number"),
    Field("disk_type_fmc", 0x17, 1, "FMC blue disk marker"),
    Field("unknown_18", 0x18, 1, "unknown, zero in known games"),
    Field("boot_file", 0x19, 1, "boot read file code"),
    Field("filler_1a", 0x1A, 5, "filler, 0xFF"),
    Field("manufacturing_date", 0x1F, 3, "manufacturing date, BCD", provenance=True),
    Field("country", 0x22, 1, "country code"),
    Field("unknown_23", 0x23, 1, "unknown, 0x61"),
    Field("unknown_24", 0x24, 1, "unknown, 0x00"),
    Field("unknown_25", 0x25, 2, "unknown, 0x00 0x02"),
    Field("unknown_27", 0x27, 5, "unknown, believed disk metadata", provenance=True),
    Field("rewritten_date", 0x2C, 3, "rewritten disk date, BCD", provenance=True),
    Field("unknown_2f", 0x2F, 1, "unknown", provenance=True),
    Field("unknown_30", 0x30, 1, "unknown, 0x80", provenance=True),
    Field("writer_serial", 0x31, 2, "Disk Writer serial number", provenance=True),
    Field("unknown_33", 0x33, 1, "unknown, 0x07", provenance=True),
    Field("rewrite_count", 0x34, 1, "disk rewrite count, BCD", provenance=True),
    Field("actual_side", 0x35, 1, "actual disk side", provenance=True),
    Field("disk_type_other", 0x36, 1, "yellow, blue or prototype", provenance=True),
    Field("disk_version", 0x37, 1, "disk version", provenance=True),
)

FIELDS_BY_NAME: Final[dict[str, Field]] = {field.name: field for field in DISK_INFO_FIELDS}

IDENTITY_FIELDS: Final[frozenset[str]] = frozenset(
    field.name for field in DISK_INFO_FIELDS if not field.provenance
)


@dataclass(frozen=True, slots=True)
class MaskProfile:
    name: str
    version: int
    masked: frozenset[str]

    @property
    def label(self) -> str:
        return f"{self.name}/v{self.version}"


RAW_PROFILE: Final = MaskProfile(name="raw", version=1, masked=frozenset())

CONTENT_PROFILE: Final = MaskProfile(
    name="content",
    version=1,
    masked=frozenset(field.name for field in DISK_INFO_FIELDS if field.provenance),
)

STAMPED_BY_THE_WRITER: Final[frozenset[str]] = frozenset(
    {"country", "unknown_23", "unknown_24", "unknown_25"}
)

RELEASE_PROFILE: Final = MaskProfile(
    name="release",
    version=1,
    masked=CONTENT_PROFILE.masked | STAMPED_BY_THE_WRITER,
)

DATA_PROFILE: Final = MaskProfile(
    name="data",
    version=1,
    masked=frozenset(field.name for field in DISK_INFO_FIELDS if field.name != "block_code"),
)

PROFILES: Final[dict[str, MaskProfile]] = {
    RAW_PROFILE.name: RAW_PROFILE,
    CONTENT_PROFILE.name: CONTENT_PROFILE,
    RELEASE_PROFILE.name: RELEASE_PROFILE,
    DATA_PROFILE.name: DATA_PROFILE,
}


def bcd_to_int(value: int) -> int | None:
    high = value >> 4
    low = value & 0x0F
    if high > MAX_BCD_DIGIT or low > MAX_BCD_DIGIT:
        return None
    return high * 10 + low


def _bcd_date(payload: bytes) -> tuple[int, int, int] | None:
    parts = [bcd_to_int(byte) for byte in payload]
    if any(part is None for part in parts):
        return None
    year, month, day = (part for part in parts if part is not None)
    return (SHOWA_EPOCH + year, month, day)


def mask_disk_info(payload: bytes, profile: MaskProfile) -> bytes:
    if len(payload) != DISK_INFO_SIZE:
        message = f"a disk info block is {DISK_INFO_SIZE} bytes, got {len(payload)}"
        raise ValueError(message)
    masked = bytearray(payload)
    for name in profile.masked:
        field = FIELDS_BY_NAME[name]
        masked[field.offset : field.offset + field.length] = bytes(field.length)
    return bytes(masked)


@dataclass(frozen=True, slots=True)
class DiskInfo:
    payload: bytes

    @classmethod
    def parse(cls, payload: bytes) -> DiskInfo:
        if len(payload) != DISK_INFO_SIZE:
            message = f"a disk info block is {DISK_INFO_SIZE} bytes, got {len(payload)}"
            raise ValueError(message)
        return cls(payload=payload)

    def raw(self, name: str) -> bytes:
        field = FIELDS_BY_NAME[name]
        return self.payload[field.offset : field.offset + field.length]

    def byte(self, name: str) -> int:
        return self.raw(name)[0]

    @property
    def verification(self) -> bytes:
        return self.raw("verification")

    @property
    def is_verified(self) -> bool:
        return self.verification == VERIFICATION_STRING

    @property
    def licensee(self) -> int:
        return self.byte("licensee")

    @property
    def game_name(self) -> str:
        return self.raw("game_name").decode("ascii", errors="replace").rstrip(" \0")

    @property
    def game_type(self) -> int:
        return self.byte("game_type")

    @property
    def game_version(self) -> int:
        return self.byte("game_version")

    @property
    def side(self) -> int:
        return self.byte("side")

    @property
    def disk_number(self) -> int:
        return self.byte("disk_number")

    @property
    def boot_file(self) -> int:
        return self.byte("boot_file")

    @property
    def country(self) -> int:
        return self.byte("country")

    @property
    def manufacturing_date(self) -> tuple[int, int, int] | None:
        return _bcd_date(self.raw("manufacturing_date"))

    @property
    def rewritten_date(self) -> tuple[int, int, int] | None:
        return _bcd_date(self.raw("rewritten_date"))

    @property
    def writer_serial(self) -> int:
        return int.from_bytes(self.raw("writer_serial"), "little")

    @property
    def rewrite_count(self) -> int | None:
        return bcd_to_int(self.byte("rewrite_count"))

    @property
    def actual_side(self) -> int:
        return self.byte("actual_side")

    @property
    def disk_type(self) -> int:
        return self.byte("disk_type_other")

    @property
    def disk_version(self) -> int:
        return self.byte("disk_version")

    def masked(self, profile: MaskProfile) -> bytes:
        return mask_disk_info(self.payload, profile)
