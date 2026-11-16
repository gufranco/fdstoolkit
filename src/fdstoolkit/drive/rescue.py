from __future__ import annotations

import io
import json
import shutil
import zipfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol, cast

from fdstoolkit.core.blocks import BlockKind, declared_blocks
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.core.diskinfo import DiskInfo
from fdstoolkit.drive.align import good_block
from fdstoolkit.drive.captures import (
    MANIFEST,
    Bundle,
    BundleError,
    Capture,
    bundle_files,
    created_now,
    load_bundle,
    read_zip,
    zip_files,
)
from fdstoolkit.drive.recovery import rebuild
from fdstoolkit.hardware.ports import BlockRead

STATE_NAME: Final = "rescue.json"
FORMAT: Final = "fdstoolkit-rescue"
FORMAT_VERSION: Final = 1
MAX_STATE_BYTES: Final = 64 * 1024
IMAGE_NAME: Final = "rescue.fds"
IDENTITY_FIELDS: Final = ("licensee", "game", "version", "disk")
NOTHING_KEPT: Final = "nothing was kept"
NO_CAPTURE: Final = (
    "the drive returned no pulse capture of this read, so there is nothing to vote with"
)


class RescueError(ValueError):
    pass


class CapturingReader(Protocol):
    @property
    def captures(self) -> tuple[Capture, ...]: ...

    def read_side(self, side: int) -> Iterator[BlockRead]: ...


@dataclass(frozen=True, slots=True)
class Identity:
    licensee: int
    game: str
    version: int
    disk: int

    def render(self) -> str:
        return f"{self.game} version {self.version}, disk {self.disk}"


@dataclass(frozen=True, slots=True)
class RescueState:
    identity: Identity | None
    infos: tuple[tuple[int, bytes], ...]
    captures: tuple[Capture, ...]

    def info_of(self, side: int) -> bytes | None:
        return next((info for number, info in self.infos if number == side), None)

    def reads_of(self, side: int) -> int:
        return sum(1 for capture in self.captures if capture.side == side)


EMPTY: Final = RescueState(identity=None, infos=(), captures=())


def identity_of(info: DiskInfo) -> Identity:
    return Identity(
        licensee=info.licensee,
        game=info.game_name,
        version=info.game_version,
        disk=info.disk_number,
    )


def _disk_info(blocks: Sequence[BlockRead]) -> DiskInfo | None:
    first = blocks[0] if blocks else None
    if first is None or not first.crc_ok or first.payload[:1] != bytes([BlockKind.DISK_INFO]):
        return None
    return DiskInfo.parse(first.payload)


def identity_problem(state: RescueState, side: int, blocks: Sequence[BlockRead]) -> str:
    info = _disk_info(blocks)
    if info is None:
        if not state.captures:
            return ""
        return (
            "the disk information did not read clean, so this read cannot be matched to the "
            f"rescue; {NOTHING_KEPT}"
        )
    if info.side != side:
        return (
            f"the disk in the drive shows side {info.side} face down, and this run reads side "
            f"{side}: turn the disk over"
        )
    found = identity_of(info)
    if state.identity is not None and found != state.identity:
        return (
            f"this rescue is of {state.identity.render()}, and the disk in the drive is "
            f"{found.render()}; {NOTHING_KEPT}"
        )
    known = state.info_of(side)
    if known is not None and known != info.payload:
        return (
            f"side {side} of the disk in the drive carries other disk information than the "
            f"rescue recorded, so it was rewritten or is another copy; {NOTHING_KEPT}"
        )
    return ""


def with_read(
    state: RescueState, side: int, blocks: Sequence[BlockRead], capture: Capture
) -> RescueState:
    kept = Capture(side=side, read=state.reads_of(side) + 1, data=capture.data)
    info = _disk_info(blocks)
    learned = info is not None and state.info_of(side) is None
    infos = (*state.infos, (side, info.payload)) if learned and info is not None else state.infos
    identity = state.identity
    if identity is None and info is not None:
        identity = identity_of(info)
    return RescueState(identity=identity, infos=infos, captures=(*state.captures, kept))


def state_bytes(state: RescueState) -> bytes:
    identity = state.identity
    document = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "identity": None
        if identity is None
        else dict(
            zip(
                IDENTITY_FIELDS,
                (identity.licensee, identity.game, identity.version, identity.disk),
                strict=True,
            )
        ),
        "sides": {str(side): info.hex() for side, info in sorted(state.infos)},
    }
    return json.dumps(document, indent=2).encode("utf-8")


def _refused() -> RescueError:
    return RescueError(f"{STATE_NAME} is not a rescue state that this toolkit wrote")


def _parsed_identity(found: object) -> Identity | None:
    if found is None:
        return None
    if not isinstance(found, dict) or set(cast("dict[str, object]", found)) != set(IDENTITY_FIELDS):
        raise _refused()
    fields = cast("dict[str, object]", found)
    licensee, game, version, disk = (fields[name] for name in IDENTITY_FIELDS)
    if not (isinstance(licensee, int) and isinstance(game, str)):
        raise _refused()
    if not (isinstance(version, int) and isinstance(disk, int)):
        raise _refused()
    return Identity(licensee=licensee, game=game, version=version, disk=disk)


def _parsed_sides(found: object) -> tuple[tuple[int, bytes], ...]:
    if not isinstance(found, dict):
        raise _refused()
    try:
        return tuple(
            (int(side), bytes.fromhex(str(info)))
            for side, info in cast("dict[str, object]", found).items()
        )
    except ValueError as error:
        raise _refused() from error


def _state(raw: bytes | None, bundle: Bundle) -> RescueState:
    if raw is None:
        return RescueState(identity=None, infos=(), captures=bundle.captures)
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise _refused() from error
    if not isinstance(document, dict):
        raise _refused()
    fields = cast("dict[str, object]", document)
    if fields.get("format") != FORMAT or fields.get("version") != FORMAT_VERSION:
        raise _refused()
    identity = _parsed_identity(fields.get("identity"))
    return RescueState(
        identity=identity, infos=_parsed_sides(fields.get("sides")), captures=bundle.captures
    )


def load_folder(folder: Path) -> RescueState:
    if not (folder / MANIFEST).is_file():
        return EMPTY
    try:
        bundle = load_bundle(folder)
    except BundleError as error:
        raise RescueError(str(error)) from error
    state = folder / STATE_NAME
    return _state(state.read_bytes() if state.is_file() else None, bundle)


def _replace(path: Path, data: bytes) -> None:
    temporary = path.with_name(f"{path.name}.tmp")
    temporary.write_bytes(data)
    if path.exists():
        shutil.copyfile(path, path.with_name(f"{path.name}.bak"))
    temporary.replace(path)


def save_folder(folder: Path, state: RescueState) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    files = bundle_files(state.captures, image=IMAGE_NAME, created=created_now())
    for capture in state.captures:
        target = folder / capture.name
        if not target.is_file():
            _replace(target, capture.data)
    _replace(folder / MANIFEST, files[MANIFEST])
    _replace(folder / STATE_NAME, state_bytes(state))


def state_zip(state: RescueState) -> bytes:
    files = bundle_files(state.captures, image=IMAGE_NAME, created=created_now())
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in {**files, STATE_NAME: state_bytes(state)}.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def load_zip(data: bytes) -> RescueState:
    try:
        bundle = read_zip(data)
        raw = zip_files(data, [STATE_NAME], limit=MAX_STATE_BYTES).get(STATE_NAME)
    except BundleError as error:
        raise RescueError(str(error)) from error
    return _state(raw, bundle)


@dataclass(frozen=True, slots=True)
class SideProgress:
    side: int
    reads: int
    declared: int
    unsettled: tuple[int, ...]

    @property
    def settled(self) -> bool:
        return self.declared > 0 and not self.unsettled

    def render(self) -> str:
        if not self.declared:
            return (
                f"side {self.side}: the declared file count has not read clean yet, after "
                f"{self.reads} read(s)"
            )
        if self.settled:
            return f"side {self.side}: every declared block settled after {self.reads} read(s)"
        blocks = ", ".join(str(block) for block in self.unsettled)
        return (
            f"side {self.side}: {len(self.unsettled)} block(s) unsettled after {self.reads} "
            f"read(s): {blocks}"
        )


@dataclass(frozen=True, slots=True)
class RescueProgress:
    disk: Disk
    sides: tuple[SideProgress, ...]
    lines: tuple[str, ...]

    @property
    def settled(self) -> bool:
        return bool(self.sides) and all(side.settled for side in self.sides)


def _declared(side: Side) -> int:
    for block in side.blocks:
        if block.kind is BlockKind.FILE_AMOUNT and good_block(block):
            return declared_blocks(block.payload)
    return 0


def _side_progress(number: int, side: Side, unresolved: Sequence[int], reads: int) -> SideProgress:
    declared = _declared(side)
    bad = {index for index, block in enumerate(side.blocks[:declared]) if not good_block(block)}
    absent = set(range(len(side.blocks), declared))
    unsettled = tuple(sorted(set(unresolved) | bad | absent)) if declared else ()
    return SideProgress(side=number, reads=reads, declared=declared, unsettled=unsettled)


def progress_of(state: RescueState) -> RescueProgress:
    bundle = Bundle(captures=state.captures, image=IMAGE_NAME, created="")
    rebuilt = rebuild(bundle)
    sides = tuple(
        _side_progress(
            number,
            side,
            [block for where, block in rebuilt.unresolved if where == number],
            state.reads_of(number),
        )
        for number, side in zip(bundle.sides, rebuilt.disk.sides, strict=True)
    )
    lines = (*rebuilt.lines, *(side.render() for side in sides))
    return RescueProgress(disk=rebuilt.disk, sides=sides, lines=lines)


def read_into(state: RescueState, reader: CapturingReader, side: int) -> RescueState:
    before = len(reader.captures)
    blocks = tuple(reader.read_side(side))
    if len(reader.captures) == before:
        raise RescueError(NO_CAPTURE)
    problem = identity_problem(state, side, blocks)
    if problem:
        raise RescueError(problem)
    return with_read(state, side, blocks, reader.captures[-1])


def side_settled(state: RescueState, side: int) -> bool:
    return any(found.side == side and found.settled for found in progress_of(state).sides)
