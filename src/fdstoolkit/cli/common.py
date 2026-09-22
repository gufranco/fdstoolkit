from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Final

import typer

from fdstoolkit.codecs import fds, qd
from fdstoolkit.codecs.foreign import ForeignImageError, reject_foreign
from fdstoolkit.core.diagnostics import Diagnostic
from fdstoolkit.core.disk import Disk

FDS_SUFFIX: Final = ".fds"
QD_SUFFIX: Final = ".qd"


class Container(StrEnum):
    FDS = "fds"
    QD = "qd"


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
    disk, findings = decoder(data)
    return disk, findings, data, container


def guard_output(output: Path, *, force: bool) -> None:
    if output.exists() and not force:
        message = f"{output} exists, pass --force to overwrite"
        raise fail(message)
