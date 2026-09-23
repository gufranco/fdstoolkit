from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import HTTPException

from fdstoolkit.build.manifest import build_from_manifest, load_manifest
from fdstoolkit.build.targets import export_for
from fdstoolkit.codecs.ares import decode_side
from fdstoolkit.codecs.mgd1 import SideFile, join_side_files, split_into_side_files
from fdstoolkit.core.bios import predict_boot
from fdstoolkit.core.blocks import FileKind
from fdstoolkit.core.disk import Disk
from fdstoolkit.edit.clean import clean_trailing_data
from fdstoolkit.edit.diskinfo import apply_edits, parse_edit
from fdstoolkit.edit.emulator import SaveFormat, extract_save, merge_save
from fdstoolkit.edit.files import FileSpec, extract_files, insert_file
from fdstoolkit.edit.multidisk import merge as merge_disks
from fdstoolkit.edit.multidisk import unmerge as unmerge_disk
from fdstoolkit.edit.rebuild import RebuildOptions, rebuild
from fdstoolkit.edit.recipes import load_recipes
from fdstoolkit.edit.saves import find_save_candidates, normalise_saves
from fdstoolkit.fdskey.card import FirmwareVariant, card_blank
from fdstoolkit.fdskey.lint import lint_card_image
from fdstoolkit.identify.provenance import provenance_of
from fdstoolkit.patch.apply import apply_patch
from fdstoolkit.quality.consensus import compare_images
from fdstoolkit.quality.layout import layout_of
from fdstoolkit.ui.schemas import (
    BuildSpec,
    CardSpec,
    DiffSpec,
    EditSpec,
    ExportSpec,
    FileResult,
    FilesResult,
    ImageSpec,
    ImagesSpec,
    InsertSpec,
    MergeSpec,
    PatchSpec,
    RebuildSpec,
    RecipeSpec,
    RowsResult,
    SaveExtractSpec,
    SaveSpec,
    SplitSpec,
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


def _disk(spec: ImageSpec) -> Disk:
    disk, _, _ = decode_payload(spec.data)
    return disk


def _emit(disk: Disk, name: str, *, headered: bool = False) -> FileResult:
    return named_file(name, encoded(disk, headered=headered))


def ls(spec: ImageSpec) -> RowsResult:
    rows: list[dict[str, Any]] = []
    for index, side in enumerate(_disk(spec).sides):
        declared = side.declared_file_count
        rows.extend(
            {
                "side": index,
                "number": header.number,
                "id": header.file_id,
                "name": header.name,
                "address": header.address,
                "kind": str(header.kind),
                "size": header.size,
                "hidden": declared is not None and position >= declared,
            }
            for position, header in enumerate(side.file_headers)
        )
    return RowsResult(rows=rows)


def diff(spec: DiffSpec) -> RowsResult:
    left, _, _ = decode_payload(spec.left)
    right, _, _ = decode_payload(spec.right)
    report = compare_images(left, right)
    return RowsResult(rows=rows_of(report.differing_blocks), ok=report.identical)


def boot(spec: ImageSpec) -> RowsResult:
    return RowsResult(rows=rows_of(predict_boot(_disk(spec)).sides))


def layout(spec: ImageSpec) -> RowsResult:
    return RowsResult(rows=rows_of(layout_of(_disk(spec)).sides))


def provenance(spec: ImageSpec) -> RowsResult:
    return RowsResult(rows=rows_of(provenance_of(_disk(spec)).sides))


def lint(spec: ImageSpec) -> RowsResult:
    _, data, _ = decode_payload(spec.data)
    findings = lint_card_image(data, name=Path(spec.name))
    return RowsResult(rows=rows_of(findings), ok=not findings)


def saves(spec: ImagesSpec) -> RowsResult:
    if not spec.images:
        refuse("comparing saves needs at least one dump", status=UNPROCESSABLE)
    disks = [decode_payload(entry)[0] for entry in spec.images]
    return RowsResult(rows=rows_of(find_save_candidates(disks)))


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


def clean(spec: ImageSpec) -> FileResult:
    updated, _ = clean_trailing_data(_disk(spec))
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


def save_apply(spec: SaveSpec) -> FileResult:
    _, data, _ = decode_payload(spec.data)
    try:
        merged = merge_save(data, bytes_of(spec.save))
    except (ValueError, IndexError, KeyError) as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return named_file(spec.name, merged)


def save_extract(spec: SaveExtractSpec) -> FileResult:
    _, data, _ = decode_payload(spec.data)
    try:
        body = extract_save(data, bytes_of(spec.played), fmt=SaveFormat(spec.fmt))
    except (ValueError, IndexError, KeyError) as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return named_file(f"{Path(spec.name).stem}.{spec.fmt}", body)


def normalise(spec: RecipeSpec) -> FileResult:
    with TemporaryDirectory(prefix="fdstoolkit-ui-") as directory:
        path = Path(directory) / "recipes.json"
        path.write_bytes(bytes_of(spec.recipes))
        try:
            recipes = load_recipes(path)
        except (ValueError, OSError, KeyError, AttributeError, TypeError) as error:
            raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    try:
        updated, _ = normalise_saves(_disk(spec), recipes)
    except (ValueError, IndexError, KeyError) as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return _emit(updated, spec.name)


def split(spec: SplitSpec) -> FilesResult:
    _, data, _ = decode_payload(spec.data)
    parts = split_into_side_files(data, stem=spec.stem)
    return FilesResult(files=[named_file(item.name, item.data) for item in parts])


def join(spec: ImagesSpec) -> FileResult:
    if not spec.images:
        refuse("joining needs at least one side file", status=UNPROCESSABLE)
    names = spec.names or [f"side{index}" for index in range(len(spec.images))]
    parts = [
        SideFile(name=name, data=bytes_of(payload))
        for name, payload in zip(names, spec.images, strict=False)
    ]
    return named_file("joined.fds", join_side_files(parts))


def merge(spec: MergeSpec) -> FileResult:
    if not spec.images:
        refuse("merging needs at least one disk", status=UNPROCESSABLE)
    disks = [decode_payload(entry)[0] for entry in spec.images]
    merged, _ = merge_disks(disks)
    return _emit(merged, "merged.fds", headered=spec.headered)


def unmerge(spec: ImageSpec) -> FilesResult:
    disks, _ = unmerge_disk(_disk(spec))
    stem = Path(spec.name).stem
    return FilesResult(
        files=[_emit(item, f"{stem}.disk{index + 1}.fds") for index, item in enumerate(disks)]
    )


def export(spec: ExportSpec) -> FilesResult:
    bios = bytes_of(spec.bios) if spec.bios else None
    with TemporaryDirectory(prefix="fdstoolkit-ui-") as directory:
        root = Path(directory)
        try:
            written = export_for(
                _disk(spec),
                target=spec.target,
                directory=root,
                stem=Path(spec.name).stem,
                bios=bios,
            )
        except (ValueError, KeyError, OSError) as error:
            raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
        return FilesResult(
            files=[named_file(str(path.relative_to(root)), path.read_bytes()) for path in written]
        )


def import_ares(spec: ImagesSpec) -> FileResult:
    if not spec.images:
        refuse("rebuilding needs at least one side file", status=UNPROCESSABLE)
    try:
        sides = [decode_side(bytes_of(entry)) for entry in spec.images]
    except (ValueError, IndexError) as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return _emit(Disk(sides=tuple(sides)), "imported.fds")


def build(spec: BuildSpec) -> FileResult:
    with TemporaryDirectory(prefix="fdstoolkit-ui-") as directory:
        path = Path(directory) / "manifest.json"
        path.write_bytes(bytes_of(spec.manifest))
        try:
            data = build_from_manifest(load_manifest(path))
        except (ValueError, KeyError, OSError) as error:
            raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return named_file("built.fds", data)


def card(spec: CardSpec) -> FileResult:
    try:
        data = card_blank(sides=spec.sides, variant=FirmwareVariant(spec.firmware))
    except ValueError as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    return named_file("card.fds", data)
