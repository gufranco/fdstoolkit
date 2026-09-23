from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from fdstoolkit.codecs import fds
from fdstoolkit.core.canon import canonicalise, digest_string, profile_by_name
from fdstoolkit.identify.hashes import digests_of
from fdstoolkit.submit.log import DumpLog

RELEASE_PROFILE: Final = "release"
EVIDENCE: Final = (
    "photographs of all sides of the packaging",
    "photographs of the physical media, with every imprinted and stamped mark legible",
    "photographs of the PCB, with all text readable and any serials on the chips",
)
JAPAN: Final = 0x49
OPTIONAL_FIELDS: Final = (
    "Dump release date",
    "Box Barcode",
)


def no_metadata() -> dict[str, str]:
    return {}


@dataclass(frozen=True, slots=True)
class FileEntry:
    name: str
    size: int
    crc32: str
    md5: str
    sha1: str
    sha256: str


@dataclass(frozen=True, slots=True)
class Submission:
    dumper: str
    log: DumpLog
    files: tuple[FileEntry, ...]
    game: str
    identity: str
    evidence: tuple[str, ...] = ()
    affiliation: str = ""
    metadata: dict[str, str] = field(default_factory=no_metadata)

    @property
    def missing_evidence(self) -> tuple[str, ...]:
        return () if self.evidence else EVIDENCE

    @property
    def tool_line(self) -> str:
        parts = [self.log.tool, self.log.backend]
        if self.log.device:
            parts.append(self.log.device)
        if self.log.settings:
            settings = ", ".join(f"{name}={value}" for name, value in self.log.settings.items())
            parts.append(f"non-default settings: {settings}")
        else:
            parts.append("default settings")
        return ", ".join(parts)

    def render(self) -> str:
        lines = [
            f"Game name: {self.game}",
            f"Dumper (person who dumped the ROM): {self.dumper}",
            f"Affiliation (if applicable): {self.affiliation}",
            f"Dump tool: {self.tool_line}",
            f"Date dump was created on (YYYY-MM-DD): {self.log.taken}",
            "",
            "Dump logs:",
            self.log.render().rstrip(),
            "",
            "--ROM(s)/file(s)--",
        ]
        for entry in self.files:
            lines.append(f"File: {entry.name}")
            lines.append(f"Size (bytes): {entry.size}")
            lines.append(f"CRC32: {entry.crc32}")
            lines.append(f"MD5 hash: {entry.md5}")
            lines.append(f"SHA-1 hash: {entry.sha1}")
            lines.append(f"SHA-256 hash: {entry.sha256}")
            lines.append("")
        lines.append(f"Links/attachments to Cart/PCB/box photos/scans: {', '.join(self.evidence)}")
        if self.missing_evidence:
            lines.append("Still needed, which this tool cannot produce:")
            lines.extend(f"  {item}" for item in self.missing_evidence)
        lines.append("")
        for label, value in self.metadata.items():
            lines.append(f"{label}: {value}")
        lines.append("")
        lines.append(f"Identity digest: {self.identity}")
        lines.append(
            "The header carries a rewrite date and a kiosk serial, so two copies of one "
            "release never share a SHA-256. The digest above masks those fields, so it "
            "does compare across copies."
        )
        return "\n".join(lines) + "\n"


def _entry(name: str, data: bytes) -> FileEntry:
    digests = digests_of(data)
    return FileEntry(
        name=name,
        size=digests.size,
        crc32=digests.crc32,
        md5=digests.md5,
        sha1=digests.sha1,
        sha256=digests.sha256,
    )


def _game_name(data: bytes) -> str:
    disk, _ = fds.decode(data)
    for side in disk.sides:
        for block in side.blocks:
            if len(block.payload) >= 19:  # noqa: PLR2004
                name = bytes(block.payload[16:19]).decode("ascii", errors="replace").strip()
                if name:
                    return name
    return "unknown"


def _metadata(data: bytes) -> dict[str, str]:
    disk, _ = fds.decode(data)
    info = disk.sides[0].disk_info if disk.sides else None
    found: dict[str, str] = {
        "Languages": "Japanese",
        "ROM Region": "Japan" if info and info.country == JAPAN else "",
        "ROM Revision": str(info.game_version) if info else "",
        "ROM Serial": info.game_name if info else "",
        "Physical Media Serial 2": f"{info.writer_serial:04x}" if info else "",
        "Physical Media Stamp": f"rewrite count {info.rewrite_count}" if info else "",
    }
    for label in OPTIONAL_FIELDS:
        found[label] = ""
    return found


def submission_for(
    data: bytes,
    *,
    name: str,
    log: DumpLog,
    dumper: str,
    affiliation: str = "",
    evidence: tuple[str, ...] = (),
    extra: dict[str, bytes] | None = None,
) -> Submission:
    if log.simulated:
        message = "this log came from a simulated drive, so there is no physical dump to submit"
        raise ValueError(message)
    if not dumper.strip():
        message = "a submission names the dumper who took it"
        raise ValueError(message)

    disk, _ = fds.decode(data)
    canonical = canonicalise(disk, profile_by_name(RELEASE_PROFILE))
    files = [_entry(name, data)]
    files.extend(_entry(other, payload) for other, payload in (extra or {}).items())

    return Submission(
        dumper=dumper.strip(),
        log=log,
        files=tuple(files),
        game=_game_name(data),
        identity=digest_string(canonical),
        evidence=evidence,
        affiliation=affiliation,
        metadata=_metadata(data),
    )
