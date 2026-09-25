from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from fastapi import HTTPException

from fdstoolkit.build.manifest import build_from_manifest, load_manifest
from fdstoolkit.build.targets import export_for
from fdstoolkit.core.bios import predict_boot
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk
from fdstoolkit.edit.diskinfo import apply_edits, parse_edit
from fdstoolkit.edit.emulator import SaveFormat, extract_save, merge_save
from fdstoolkit.edit.files import FileSpec, extract_files, insert_file
from fdstoolkit.edit.rebuild import RebuildOptions, rebuild
from fdstoolkit.edit.recipes import load_recipes
from fdstoolkit.edit.saves import SaveRecipe, find_save_candidates, normalise_saves
from fdstoolkit.identify.provenance import provenance_of
from fdstoolkit.patch.apply import apply_patch
from fdstoolkit.quality.consensus import compare_images
from fdstoolkit.quality.explain import explain
from fdstoolkit.ui.schemas import (
    BuildSpec,
    DiffResult,
    DiffSpec,
    EditSpec,
    ExportSpec,
    FileResult,
    FilesResult,
    ImageSpec,
    InsertSpec,
    PatchSpec,
    RebuildSpec,
    RowsResult,
    SaveSpec,
)
from fdstoolkit.ui.shared import (
    BAD_REQUEST,
    UNPROCESSABLE,
    bytes_of,
    decode_payload,
    encoded,
    named_file,
    refuse,
    rows_of,
)

KIND_BY_NAME = {
    "program": FileKind.PROGRAM,
    "character": FileKind.CHARACTER,
    "nametable": FileKind.NAMETABLE,
}


MIN_DUMPS: Final = 2


def _disk(spec: ImageSpec) -> Disk:
    disk, _, _ = decode_payload(spec.data)
    return disk


def _emit(disk: Disk, name: str, *, headered: bool = False) -> FileResult:
    return named_file(name, encoded(disk, headered=headered))


def diff(spec: DiffSpec) -> DiffResult:
    left, _, _ = decode_payload(spec.left)
    right, _, _ = decode_payload(spec.right)
    report = compare_images(left, right)
    blocks = [{"side": side, "block": block} for side, block in report.differing_blocks]
    if not spec.explain:
        return DiffResult(
            headline=report.summary,
            identical=report.identical,
            blocks=blocks,
            ok=report.identical,
        )
    reading = explain(left, right)
    return DiffResult(
        headline=reading.headline,
        identical=reading.identical,
        same_software=reading.same_software,
        blocks=blocks,
        differences=rows_of(reading.fields),
        file_changes=rows_of(reading.files),
        ok=reading.identical,
    )


def boot(spec: ImageSpec) -> RowsResult:
    return RowsResult(rows=rows_of(predict_boot(_disk(spec)).sides))


def provenance(spec: ImageSpec) -> RowsResult:
    return RowsResult(rows=rows_of(provenance_of(_disk(spec)).sides))


def extract(spec: ImageSpec) -> FilesResult:
    return FilesResult(
        files=[named_file(entry.name, entry.data) for entry in extract_files(_disk(spec))]
    )


def insert(spec: InsertSpec) -> FileResult:
    kind = KIND_BY_NAME.get(spec.kind)
    if kind is None:
        refuse(f"there is no file kind called {spec.kind}")
    updated = insert_file(
        _disk(spec),
        side=spec.side,
        spec=FileSpec(
            name=spec.file_name,
            address=spec.address,
            kind=kind,
            data=bytes_of(spec.file),
        ),
    )
    return _emit(updated, spec.name)


def edit(spec: EditSpec) -> FileResult:
    try:
        edits = dict(parse_edit(entry) for entry in spec.edits)
        updated, _ = apply_edits(_disk(spec), side=spec.side, edits=edits)
    except (ValueError, KeyError, IndexError) as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return _emit(updated, spec.name)


def rebuild_image(spec: RebuildSpec) -> FileResult:
    updated, _ = rebuild(
        _disk(spec),
        options=RebuildOptions(
            keep_tail=spec.keep_tail,
            reveal_hidden=spec.reveal_hidden,
            drop_hidden=spec.drop_hidden,
            renumber=spec.renumber,
        ),
    )
    return _emit(updated, spec.name)


def patch(spec: PatchSpec) -> FileResult:
    _, data, _ = decode_payload(spec.data)
    try:
        outcome = apply_patch(bytes_of(spec.patch), data)
    except (ValueError, IndexError, KeyError) as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return named_file(spec.name, outcome.data)


def export(spec: ExportSpec) -> FilesResult:
    with TemporaryDirectory(prefix="fdstoolkit-ui-") as directory:
        root = Path(directory)
        try:
            written = export_for(
                _disk(spec),
                target=spec.target,
                directory=root,
                stem=Path(spec.name).stem,
            )
        except (ValueError, KeyError, OSError) as error:
            raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
        return FilesResult(
            files=[named_file(str(path.relative_to(root)), path.read_bytes()) for path in written]
        )


def build(spec: BuildSpec) -> FileResult:
    with TemporaryDirectory(prefix="fdstoolkit-ui-") as directory:
        path = Path(directory) / "manifest.json"
        path.write_bytes(bytes_of(spec.manifest))
        try:
            data = build_from_manifest(load_manifest(path))
        except (ValueError, KeyError, OSError) as error:
            raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return named_file("built.fds", data)


def _recipes(data: str) -> tuple[SaveRecipe, ...]:
    with TemporaryDirectory(prefix="fdstoolkit-ui-") as directory:
        path = Path(directory) / "recipes.json"
        path.write_bytes(bytes_of(data))
        try:
            return load_recipes(path)
        except (ValueError, OSError, KeyError, AttributeError, TypeError) as error:
            raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error


def _needed(value: str | None, what: str, action: str) -> str:
    if value is None:
        refuse(f"save {action} needs {what}", status=UNPROCESSABLE)
    return value


def _only_image(spec: SaveSpec) -> str:
    if len(spec.images) != 1:
        refuse(f"save {spec.action} works on one image", status=UNPROCESSABLE)
    return spec.images[0]


def _save_find(spec: SaveSpec) -> RowsResult:
    if len(spec.images) < MIN_DUMPS:
        refuse("save find compares two or more dumps of one release", status=UNPROCESSABLE)
    candidates = find_save_candidates([decode_payload(entry)[0] for entry in spec.images])
    headline = (
        "no save candidate: every file agrees across the dumps"
        if not candidates
        else f"{len(candidates)} file(s) differ across the dumps and could hold the save"
    )
    return RowsResult(headline=headline, rows=rows_of(candidates))


def _save_apply(spec: SaveSpec) -> FileResult:
    _, data, _ = decode_payload(_only_image(spec))
    save = _needed(spec.save, "a save", "apply")
    try:
        merged = merge_save(data, bytes_of(save))
    except (ValueError, IndexError, KeyError) as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return named_file(spec.name, merged)


def _save_extract(spec: SaveSpec) -> FileResult:
    _, data, _ = decode_payload(_only_image(spec))
    played = _needed(spec.played, "the played image", "extract")
    try:
        body = extract_save(data, bytes_of(played), fmt=SaveFormat(spec.save_as))
    except (ValueError, IndexError, KeyError) as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return named_file(f"{Path(spec.name).stem}.{spec.save_as}", body)


def _save_blank(spec: SaveSpec) -> FileResult:
    disk, _, _ = decode_payload(_only_image(spec))
    recipes = _recipes(_needed(spec.recipes, "a recipe file", "blank"))
    try:
        updated, _ = normalise_saves(disk, recipes)
    except (ValueError, IndexError, KeyError) as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return _emit(updated, spec.name)


SAVE_ACTIONS: Final[dict[str, Callable[[SaveSpec], RowsResult | FileResult]]] = {
    "find": _save_find,
    "apply": _save_apply,
    "extract": _save_extract,
    "blank": _save_blank,
}


def save(spec: SaveSpec) -> RowsResult | FileResult:
    action = SAVE_ACTIONS.get(spec.action)
    if action is None:
        refuse(f"save takes {', '.join(SAVE_ACTIONS)}, not {spec.action}")
    return action(spec)
