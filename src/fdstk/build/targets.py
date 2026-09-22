from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Final

from fdstk.codecs.ares import split_for_ares
from fdstk.codecs.fds import encode
from fdstk.core.disk import Disk
from fdstk.identify.firmware import extract_bios

SWAP_EXCEPTIONS: Final = "swap_exceptions.json"


@dataclass(frozen=True, slots=True)
class Target:
    name: str
    description: str
    per_side_files: bool
    bios_path: str | None
    source: str


TARGETS: Final[Mapping[str, Target]] = {
    "nt-mini": Target(
        name="nt-mini",
        description="Analogue Nt Mini Noir jailbreak: headerless, a whole number of 65500-byte sides",
        per_side_files=False,
        bios_path="BIOS/fds.bin",
        source="https://github.com/SmokeMonsterPacks/Nt-Mini-Noir-Jailbreak",
    ),
    "mister": Target(
        name="mister",
        description="MiSTer NES core: a .fds file, the BIOS beside the games as boot0.rom",
        per_side_files=False,
        bios_path="boot0.rom",
        source="https://github.com/MiSTer-devel/NES_MiSTer/blob/master/README.md",
    ),
    "everdrive-n8-pro": Target(
        name="everdrive-n8-pro",
        description="EverDrive N8 Pro: a .fds file, the BIOS in /EDN8/syscore",
        per_side_files=False,
        bios_path="EDN8/syscore/disksys.rom",
        source="https://krikzz.com/pub/support/everdrive-n8/pro-series/n8-pro-manual.pdf",
    ),
    "mesen2": Target(
        name="mesen2",
        description="Mesen2: a .fds file, the BIOS as disksys.rom in its firmware folder",
        per_side_files=False,
        bios_path="disksys.rom",
        source="https://github.com/SourMesen/Mesen2/blob/master/Core/Shared/FirmwareHelper.h",
    ),
    "fceux": Target(
        name="fceux",
        description="FCEUX: a .fds file, the BIOS as an exactly 8192-byte disksys.rom",
        per_side_files=False,
        bios_path="disksys.rom",
        source="https://github.com/TASEmulators/fceux/blob/master/src/fds.cpp",
    ),
    "ares": Target(
        name="ares",
        description="ares: one 73728-byte file per side, with gaps and checksums",
        per_side_files=True,
        bios_path=None,
        source="https://github.com/ares-emulator/ares/blob/master/mia/medium/famicom-disk-system.cpp",
    ),
}


def _target(name: str) -> Target:
    target = TARGETS.get(name)
    if target is None:
        known = ", ".join(sorted(TARGETS))
        message = f"unknown target {name}, known targets are {known}"
        raise ValueError(message)
    return target


def _write(path: Path, data: bytes, *, force: bool) -> Path:
    if path.exists() and not force:
        message = f"{path} exists"
        raise FileExistsError(message)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def export_for(
    disk: Disk,
    *,
    target: str,
    directory: Path,
    stem: str,
    bios: bytes | None = None,
    force: bool = False,
) -> tuple[Path, ...]:
    chosen = _target(target)
    if bios is not None and chosen.bios_path is None:
        message = f"{chosen.name} does not take a BIOS, it emulates the disk system itself"
        raise ValueError(message)
    clean_bios = extract_bios(bios) if bios is not None else None

    written: list[Path] = []
    if chosen.per_side_files:
        folder = directory / stem
        written.extend(
            _write(folder / name, data, force=force)
            for name, data in split_for_ares(disk).items()
        )
    else:
        data, _ = encode(disk, headered=False)
        written.append(_write(directory / f"{stem}.fds", data, force=force))

    if clean_bios is not None and chosen.bios_path is not None:
        written.append(_write(directory / chosen.bios_path, clean_bios, force=force))

    return tuple(written)


def _exceptions() -> dict[str, Any]:
    text = resources.files("fdstk.data").joinpath(SWAP_EXCEPTIONS).read_text(encoding="utf-8")
    loaded: dict[str, Any] = json.loads(text)
    return loaded


def swap_warnings(title: str, *, target: str) -> tuple[str, ...]:
    entry: dict[str, Any] | None = _exceptions()["targets"].get(target)
    if entry is None:
        return ()
    lowered = title.lower()
    titles: list[str] = entry["titles"]
    return tuple(
        f"{name} does not work with {target}'s automatic side swap: {entry['reason']}"
        for name in titles
        if name.lower() in lowered
    )
