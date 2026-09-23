from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from fdstoolkit.hardware.session import DumpResult
from fdstoolkit.version import VERSION

LOG_VERSION: Final = 1
SIMULATED_WARNING: Final = "this dump came from a simulated drive and describes no physical disk"


def _no_settings() -> dict[str, Any]:
    return {}


@dataclass(frozen=True, slots=True)
class BlockNote:
    side: int
    block: int
    attempts: int
    recovered: bool


@dataclass(frozen=True, slots=True)
class SideNote:
    index: int
    blocks: int
    marginal: tuple[BlockNote, ...]
    failed: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class DumpLog:
    tool: str
    backend: str
    taken: str
    sides: tuple[SideNote, ...]
    grade: str
    device: str | None = None
    settings: dict[str, Any] = field(default_factory=_no_settings)
    simulated: bool = False

    @property
    def retried_blocks(self) -> tuple[BlockNote, ...]:
        return tuple(note for side in self.sides for note in side.marginal)

    @property
    def failed_blocks(self) -> tuple[tuple[int, int], ...]:
        return tuple((side.index, block) for side in self.sides for block in side.failed)

    @property
    def clean(self) -> bool:
        return not self.failed_blocks

    def as_dict(self) -> dict[str, Any]:
        return {
            "log_version": LOG_VERSION,
            "tool": self.tool,
            "backend": self.backend,
            "device": self.device,
            "taken": self.taken,
            "simulated": self.simulated,
            "settings": dict(self.settings),
            "grade": self.grade,
            "sides": [
                {
                    "index": side.index,
                    "blocks": side.blocks,
                    "marginal": [
                        {"block": note.block, "attempts": note.attempts} for note in side.marginal
                    ],
                    "failed": list(side.failed),
                }
                for side in self.sides
            ],
        }

    def as_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2) + "\n"

    def render(self) -> str:
        lines = [f"tool      {self.tool}", f"backend   {self.backend}"]
        if self.device:
            lines.append(f"device    {self.device}")
        lines.append(f"taken     {self.taken}")
        if self.simulated:
            lines.append(f"warning   {SIMULATED_WARNING}")
        lines.extend(f"setting   {name} = {value}" for name, value in self.settings.items())
        for side in self.sides:
            lines.append(f"side {side.index}    {side.blocks} blocks read")
            for note in side.marginal:
                state = "recovered" if note.recovered else "still bad"
                lines.append(f"  block {note.block} needed {note.attempts} attempts, {state}")
            lines.extend(f"  block {block} never read cleanly" for block in side.failed)
        lines.append(f"grade     {self.grade}")
        return "\n".join(lines) + "\n"


def _today() -> str:
    return datetime.now(tz=UTC).date().isoformat()


def log_of(
    result: DumpResult,
    *,
    backend: str,
    device: str | None = None,
    settings: dict[str, Any] | None = None,
    simulated: bool = False,
    taken: str | None = None,
) -> DumpLog:
    sides = tuple(
        SideNote(
            index=side.index,
            blocks=len(side.blocks),
            marginal=tuple(
                BlockNote(
                    side=side.index,
                    block=block.index,
                    attempts=block.attempts,
                    recovered=block.crc_ok,
                )
                for block in side.blocks
                if block.attempts > 1
            ),
            failed=side.failed_blocks,
        )
        for side in result.sides
    )
    return DumpLog(
        tool=f"fdstoolkit {VERSION}",
        backend=backend,
        device=device,
        taken=taken or _today(),
        sides=sides,
        grade=str(result.grade),
        settings=settings or {},
        simulated=simulated,
    )


def load_log(text: str) -> DumpLog:
    data = json.loads(text)
    version = data.get("log_version")
    if version != LOG_VERSION:
        message = f"this log is version {version}, and this build reads version {LOG_VERSION}"
        raise ValueError(message)
    sides = tuple(
        SideNote(
            index=side["index"],
            blocks=side["blocks"],
            marginal=tuple(
                BlockNote(
                    side=side["index"],
                    block=note["block"],
                    attempts=note["attempts"],
                    recovered=True,
                )
                for note in side["marginal"]
            ),
            failed=tuple(side["failed"]),
        )
        for side in data["sides"]
    )
    return DumpLog(
        tool=data["tool"],
        backend=data["backend"],
        device=data.get("device"),
        taken=data["taken"],
        sides=sides,
        grade=data["grade"],
        settings=data.get("settings", {}),
        simulated=data.get("simulated", False),
    )
