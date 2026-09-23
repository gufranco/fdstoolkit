from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, Final, cast, get_type_hints

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from fdstoolkit.core.diskinfo import PROFILES
from fdstoolkit.flux.load import CaptureFormat
from fdstoolkit.quality.surface import Finish

FIELD_KINDS: Final = ("file", "files", "text", "number", "flag", "choice", "auto")

DERIVED_FROM_FILE: Final = "name"

FILE_FIELDS: Final = frozenset(
    {
        "data",
        "source",
        "left",
        "right",
        "file",
        "save",
        "played",
        "patch",
        "dat",
        "log",
        "recipes",
        "manifest",
        "reference",
        "bios",
    }
)

FILE_LIST_FIELDS: Final = frozenset({"images", "reads", "donors", "captures"})

CHOICES: Final[dict[str, tuple[str, ...]]] = {
    "profile": tuple(sorted(PROFILES)),
    "fmt": ("", *sorted(str(item) for item in CaptureFormat)),
    "finish": tuple(str(item) for item in Finish),
    "kind": ("program", "character", "nametable"),
    "target": ("nt-mini", "mister", "everdrive-n8-pro", "mesen2", "fceux", "ares"),
    "firmware": ("released", "master"),
}


IMAGE_SUFFIXES: Final = ".fds,.qd"

ACCEPTS: Final[dict[str, str]] = {
    "data": IMAGE_SUFFIXES,
    "source": IMAGE_SUFFIXES,
    "left": IMAGE_SUFFIXES,
    "right": IMAGE_SUFFIXES,
    "file": IMAGE_SUFFIXES,
    "played": IMAGE_SUFFIXES,
    "images": IMAGE_SUFFIXES,
    "reads": IMAGE_SUFFIXES,
    "donors": IMAGE_SUFFIXES,
    "captures": ".scp,.raw,.hfe",
    "dat": ".dat,.xml",
    "save": ".ips,.ups,.fds",
    "patch": ".ips,.bps,.xdelta",
    "recipes": ".json",
    "manifest": ".json",
    "log": ".json",
    "bios": ".bin,.rom",
}


class FormField(BaseModel):
    name: str
    kind: str
    required: bool
    accepts: str = ""
    default: Any = None
    options: list[str] = []


class CommandForm(BaseModel):
    command: str
    route: str
    method: str
    family: str
    summary: str
    needs_hardware: bool = False
    fields: list[FormField] = []


def _opens_a_drive(callback: Callable[..., object]) -> bool:
    return "open_drive(" in inspect.getsource(callback)


def _kind(name: str, annotation: object) -> str:
    if name in FILE_FIELDS:
        return "file"
    if name in FILE_LIST_FIELDS:
        return "files"
    if name in CHOICES:
        return "choice"
    text = str(annotation)
    if "bool" in text:
        return "flag"
    if "int" in text or "float" in text:
        return "number"
    return "text"


def _carries_a_file(model: type[BaseModel]) -> bool:
    return any(name in FILE_FIELDS or name in FILE_LIST_FIELDS for name in model.model_fields)


def _fields(model: type[BaseModel]) -> list[FormField]:
    derived = _carries_a_file(model)
    built: list[FormField] = []
    for name, info in model.model_fields.items():
        required = info.default is PydanticUndefined and info.default_factory is None
        default = None if required else info.default
        if default is PydanticUndefined:
            default = None
        built.append(
            FormField(
                name=name,
                kind="auto"
                if derived and name == DERIVED_FROM_FILE
                else _kind(name, info.annotation),
                required=required,
                accepts=ACCEPTS.get(name, ""),
                default=default,
                options=list(CHOICES.get(name, ())),
            )
        )
    return built


def _endpoints() -> dict[str, Callable[..., object]]:
    from fdstoolkit.ui.app import create_app  # noqa: PLC0415

    found: dict[str, Callable[..., object]] = {}
    for route in create_app().routes:
        path = getattr(route, "path", "")
        endpoint = getattr(route, "endpoint", None)
        if isinstance(path, str) and endpoint is not None:
            found[path] = endpoint
    return found


def model_for(endpoint: Callable[..., object]) -> type[BaseModel] | None:
    hints = get_type_hints(endpoint)
    for name, hint in hints.items():
        if name == "return":
            continue
        if isinstance(hint, type) and issubclass(hint, BaseModel):
            return hint
    return None


def _described() -> dict[str, tuple[str, str, bool]]:
    from fdstoolkit.cli.main import app  # noqa: PLC0415

    found: dict[str, tuple[str, str, bool]] = {}
    for registered in app.registered_commands:
        callback = cast("Callable[..., object]", registered.callback)
        name = registered.name or callback.__name__.replace("_", "-")
        spoken = registered.help or callback.__doc__ or ""
        module = callback.__module__.rsplit(".", maxsplit=1)[-1]
        family = module.removesuffix("_cmds").removesuffix("_cli")
        found[name] = (family, " ".join(spoken.split()), _opens_a_drive(callback))
    return found


def form_for(command: str) -> CommandForm:
    from fdstoolkit.ui.app import ROUTE_FOR_COMMAND  # noqa: PLC0415

    route = ROUTE_FOR_COMMAND[command]
    endpoint = _endpoints().get(route)
    model = model_for(endpoint) if endpoint is not None else None
    family, summary, hardware = _described().get(command, ("other", "", False))
    return CommandForm(
        command=command,
        route=route,
        method="GET" if model is None else "POST",
        family=family,
        summary=summary,
        needs_hardware=hardware,
        fields=[] if model is None else _fields(model),
    )


def forms() -> list[CommandForm]:
    from fdstoolkit.ui.app import ROUTE_FOR_COMMAND  # noqa: PLC0415

    return [form_for(command) for command in sorted(ROUTE_FOR_COMMAND)]
