from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Final

from fdstoolkit.codecs.fds import encode
from fdstoolkit.core.disk import Disk
from fdstoolkit.identify.firmware import extract_bios

SWAP_EXCEPTIONS: Final = "swap_exceptions.json"


@dataclass(frozen=True, slots=True)
class Target:
    name: str
    description: str
    bios_path: str
    source: str


TARGETS: Final[Mapping[str, Target]] = {
    "nt-mini": Target(
        name="nt-mini",
        description=(
            "Analogue Nt Mini Noir jailbreak: headerless, a whole number of 65500-byte sides"
        ),
        bios_path="BIOS/fds.bin",
        source="https://github.com/SmokeMonsterPacks/Nt-Mini-Noir-Jailbreak",
    ),
    "mister": Target(
        name="mister",
        description="MiSTer NES core: a .fds file, the BIOS beside the games as boot0.rom",
        bios_path="boot0.rom",
        source="https://github.com/MiSTer-devel/NES_MiSTer/blob/master/README.md",
    ),
    "everdrive-n8-pro": Target(
        name="everdrive-n8-pro",
        description="EverDrive N8 Pro: a .fds file, the BIOS in /EDN8/syscore",
        bios_path="EDN8/syscore/disksys.rom",
        source="https://krikzz.com/pub/support/everdrive-n8/pro-series/n8-pro-manual.pdf",
    ),
    "mesen2": Target(
        name="mesen2",
        description="Mesen2: a .fds file, the BIOS as disksys.rom in its firmware folder",
        bios_path="disksys.rom",
        source="https://github.com/SourMesen/Mesen2/blob/master/Core/Shared/FirmwareHelper.h",
    ),
    "fceux": Target(
        name="fceux",
        description="FCEUX: a .fds file, the BIOS as an exactly 8192-byte disksys.rom",
        bios_path="disksys.rom",
        source="https://github.com/TASEmulators/fceux/blob/master/src/fds.cpp",
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
    clean_bios = extract_bios(bios) if bios is not None else None

    written: list[Path] = []
    data, _ = encode(disk, headered=False)
    written.append(_write(directory / f"{stem}.fds", data, force=force))

    if clean_bios is not None:
        written.append(_write(directory / chosen.bios_path, clean_bios, force=force))

    return tuple(written)


def _exceptions() -> dict[str, Any]:
    text = resources.files("fdstoolkit.data").joinpath(SWAP_EXCEPTIONS).read_text(encoding="utf-8")
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
