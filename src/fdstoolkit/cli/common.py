from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Final

import typer

from fdstoolkit.codecs import fds, qd
from fdstoolkit.codecs.foreign import ForeignImageError, reject_foreign
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.diagnostics import Diagnostic, Severity, worst_severity
from fdstoolkit.core.disk import Disk, Side

FDS_SUFFIX: Final = ".fds"
QD_SUFFIX: Final = ".qd"


class Family(StrEnum):
    INSPECT = "Inspect"
    CHECK = "Check"
    REPAIR = "Repair"
    CONTAINER = "Container"
    IDENTIFY = "Identify"
    HARDWARE = "Hardware"


class Container(StrEnum):
    FDS = "fds"
    QD = "qd"


class KindChoice(StrEnum):
    PROGRAM = "program"
    CHARACTER = "character"
    NAMETABLE = "nametable"


class TargetChoice(StrEnum):
    NT_MINI = "nt-mini"
    MISTER = "mister"
    EVERDRIVE_N8_PRO = "everdrive-n8-pro"
    MESEN2 = "mesen2"
    FCEUX = "fceux"


KIND_FOR_CHOICE: Final[dict[KindChoice, FileKind]] = {
    KindChoice.PROGRAM: FileKind.PROGRAM,
    KindChoice.CHARACTER: FileKind.CHARACTER,
    KindChoice.NAMETABLE: FileKind.NAMETABLE,
}


def fail(message: str) -> typer.Exit:
    typer.echo(message)
    return typer.Exit(code=1)


def container_of(path: Path) -> Container:
    suffix = path.suffix.lower()
    if suffix == FDS_SUFFIX:
        return Container.FDS
    if suffix == QD_SUFFIX:
        return Container.QD
    message = f"unknown format for {path.name}, expected a {FDS_SUFFIX} or {QD_SUFFIX} file"
    raise fail(message)


def read_image(path: Path) -> tuple[bytes, Container]:
    if not path.is_file():
        message = f"file not found: {path}"
        raise fail(message)
    return path.read_bytes(), container_of(path)


def decode_image(path: Path) -> tuple[Disk, tuple[Diagnostic, ...], bytes, Container]:
    data, container = read_image(path)
    try:
        reject_foreign(data)
    except ForeignImageError as error:
        raise fail(str(error)) from error
    decoder = fds.decode if container is Container.FDS else qd.decode
    try:
        disk, findings = decoder(data)
    except ValueError as error:
        raise fail(str(error)) from error
    return disk, findings, data, container


def guard_output(output: Path, *, force: bool) -> None:
    if output.exists() and not force:
        message = f"{output} exists, pass --force to overwrite"
        raise fail(message)


def exit_code(findings: tuple[Diagnostic, ...], *, strict: bool) -> int:
    worst = worst_severity(findings)
    if worst is Severity.ERROR:
        return 1
    if strict and worst is Severity.WARNING:
        return 1
    return 0


def writer_for(path: Path) -> Callable[[bytes], None]:
    def write(data: bytes) -> None:
        path.write_bytes(data)

    return write


def side_summary(index: int, side: Side) -> dict[str, object]:
    info = side.disk_info
    manufactured = info.manufacturing_date if info else None
    rewritten = info.rewritten_date if info else None
    return {
        "index": index,
        "formatted": side.is_formatted,
        "game_name": info.game_name if info else None,
        "game_version": info.game_version if info else None,
        "side": info.side if info else None,
        "disk_number": info.disk_number if info else None,
        "manufacturing_date": list(manufactured) if manufactured else None,
        "rewritten_date": list(rewritten) if rewritten else None,
        "rewrite_count": info.rewrite_count if info else None,
        "writer_serial": info.writer_serial if info else None,
        "declared_files": side.declared_file_count,
        "files": side.file_count,
        "hidden_files": side.hidden_file_count,
        "data_after_last_block": side.has_data_after_last_block,
    }
