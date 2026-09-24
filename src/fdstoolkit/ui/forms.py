from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, Final, cast, get_type_hints

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from fdstoolkit.build.targets import TARGETS
from fdstoolkit.cli.common import Family
from fdstoolkit.core.disk import SIDES_PER_DISK
from fdstoolkit.core.diskinfo import PROFILES
from fdstoolkit.quality.surface import Finish

FIELD_KINDS: Final = ("file", "files", "text", "number", "flag", "choice", "auto")

DERIVED_FROM_FILE: Final = "name"


FILE_FIELDS: Final = frozenset(
    {
        "data",
        "capture",
        "left",
        "right",
        "file",
        "save",
        "played",
        "patch",
        "dat",
        "recipes",
        "manifest",
        "reference",
        "bios",
    }
)

UNGROUPED: Final = "other"
ANSWERED_BY_DIALOG: Final = frozenset({"confirm"})
FAMILY_ORDER: Final = tuple(family.value.lower() for family in Family)
FILE_LIST_FIELDS: Final = frozenset({"images", "reads", "donors"})

CHOICES: Final[dict[str, tuple[str, ...]]] = {
    "profile": tuple(sorted(PROFILES)),
    "save_as": ("ips", "ups", "image"),
    "across": ("disk", "corpus"),
    "finish": tuple(str(item) for item in Finish),
    "kind": ("program", "character", "nametable"),
    "target": tuple(TARGETS),
    "firmware": ("released", "master"),
    "sides": tuple(str(count) for count in range(1, SIDES_PER_DISK + 1)),
}


IMAGE_SUFFIXES: Final = ".fds,.qd"

ACCEPTS: Final[dict[str, str]] = {
    "data": IMAGE_SUFFIXES,
    "left": IMAGE_SUFFIXES,
    "right": IMAGE_SUFFIXES,
    "file": IMAGE_SUFFIXES,
    "played": IMAGE_SUFFIXES,
    "images": IMAGE_SUFFIXES,
    "reads": IMAGE_SUFFIXES,
    "donors": IMAGE_SUFFIXES,
    "capture": ".raw03",
    "dat": ".dat,.xml",
    "save": ".ips,.ups,.fds",
    "patch": ".ips,.bps,.xdelta",
    "recipes": ".json",
    "manifest": ".json",
    "bios": ".bin,.rom",
}


class FormField(BaseModel):
    name: str
    kind: str
    required: bool
    accepts: str = ""
    default: Any = None
    options: list[str] = []
    minimum: float | None = None
    maximum: float | None = None
    above: float | None = None
    below: float | None = None
    step: float | None = None
    min_length: int | None = None
    max_length: int | None = None
    hidden: bool = False


class CommandForm(BaseModel):
    command: str
    route: str
    method: str
    family: str
    summary: str
    needs_hardware: bool = False
    fields: list[FormField] = []


def opens_a_drive(callback: Callable[..., object]) -> bool:
    try:
        return "open_drive(" in inspect.getsource(callback)
    except OSError:
        return True


class Bounds(BaseModel):
    minimum: float | None = None
    maximum: float | None = None
    above: float | None = None
    below: float | None = None
    min_length: int | None = None
    max_length: int | None = None


NUMERIC_RULES: Final = (("ge", "minimum"), ("gt", "above"), ("le", "maximum"), ("lt", "below"))

LENGTH_RULES: Final = (("min_length", "min_length"), ("max_length", "max_length"))


def _bounds(info: object) -> Bounds:
    found = Bounds()
    for rule in getattr(info, "metadata", ()):
        for attribute, key in NUMERIC_RULES:
            value = getattr(rule, attribute, None)
            if value is not None:
                found = found.model_copy(update={key: float(value)})
        for attribute, key in LENGTH_RULES:
            value = getattr(rule, attribute, None)
            if value is not None:
                found = found.model_copy(update={key: int(value)})
    return found


def _named_kind(name: str) -> str:
    if name in FILE_FIELDS:
        return "file"
    if name in FILE_LIST_FIELDS:
        return "files"
    return "choice" if name in CHOICES else ""


def _kind(name: str, annotation: object) -> str:
    named = _named_kind(name)
    if named:
        return named
    text = str(annotation)
    if "bool" in text:
        return "flag"
    return "number" if "int" in text or "float" in text else "text"


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
                step=1 if "int" in str(info.annotation) else None,
                hidden=name in ANSWERED_BY_DIALOG,
                **_bounds(info).model_dump(),
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
        family = str(registered.rich_help_panel or UNGROUPED).lower()
        found[name] = (family, " ".join(spoken.split()), opens_a_drive(callback))
    return found


def form_for(command: str) -> CommandForm:
    from fdstoolkit.ui.app import ROUTE_FOR_COMMAND  # noqa: PLC0415

    route = ROUTE_FOR_COMMAND[command]
    endpoint = _endpoints().get(route)
    model = model_for(endpoint) if endpoint is not None else None
    family, summary, hardware = _described().get(command, (UNGROUPED, "", False))
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
