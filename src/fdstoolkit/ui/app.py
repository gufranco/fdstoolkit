from __future__ import annotations

import base64
import binascii
from collections.abc import Awaitable, Callable
from hashlib import sha256
from importlib import resources
from pathlib import Path
from typing import Final

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs import fds, qd
from fdstoolkit.codecs.foreign import ForeignImageError, reject_foreign
from fdstoolkit.codecs.qd import CrcMode
from fdstoolkit.core.canon import canonicalise, digest_string, profile_by_name, restore
from fdstoolkit.core.diagnostics import Diagnostic, worst_severity
from fdstoolkit.core.disk import Disk
from fdstoolkit.core.diskinfo import PROFILES, MaskProfile
from fdstoolkit.doctor import CheckStatus, diagnose
from fdstoolkit.drive.advise import advise
from fdstoolkit.drive.classes import measure_classes
from fdstoolkit.drive.speed import from_cycles
from fdstoolkit.flux.analysis import analyse_capture
from fdstoolkit.flux.load import CaptureFormat, detect_format, load_capture
from fdstoolkit.flux.model import FluxCapture
from fdstoolkit.identify.hashes import digests_of, retroachievements_hash, side_digests
from fdstoolkit.quality.confidence import score_disk
from fdstoolkit.quality.grade import grade_disk
from fdstoolkit.quality.reads import compare_reads
from fdstoolkit.ui import analysis_routes, hardware_routes, image_routes
from fdstoolkit.ui.forms import forms
from fdstoolkit.ui.schemas import (
    BlankSpec,
    CanonSpec,
    CaptureSpec,
    Catalogue,
    ClassesResult,
    ConvertSpec,
    CyclesSpec,
    DiagnosticView,
    DigestView,
    DiskView,
    DoctorCheck,
    DoctorResult,
    FileResult,
    FluxResult,
    GradeResult,
    GradeSpec,
    HardwareResult,
    HashResult,
    HashSpec,
    ImageSpec,
    ProfileView,
    ReadsResult,
    ReadsSpec,
    SpeedView,
    TuneResult,
    VerifyResult,
    VerifySpec,
)
from fdstoolkit.version import VERSION

BAD_REQUEST: Final = 400
UNPROCESSABLE: Final = 422
STATIC_DIR: Final = Path(str(resources.files("fdstoolkit.ui") / "static"))
STAMP_LENGTH: Final = 12


def asset_stamp() -> str:
    digest = sha256()
    for path in sorted(STATIC_DIR.iterdir()):
        if path.is_file():
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()[:STAMP_LENGTH]


ASSET_STAMP: Final = asset_stamp()
ASSET_ROOT: Final = f"/assets/{ASSET_STAMP}"
A_YEAR: Final = 31536000
SIDE_SIZE: Final = fds.SIDE_SIZE
MIN_READS: Final = 2
EXPORT_TARGETS: Final = (
    "nt-mini",
    "mister",
    "everdrive-n8-pro",
    "mesen2",
    "fceux",
    "ares",
)

ROUTE_FOR_COMMAND: Final[dict[str, str]] = {
    "doctor": "/api/doctor",
    "info": "/api/info",
    "ls": "/api/ls",
    "verify": "/api/verify",
    "hash": "/api/hash",
    "diff": "/api/diff",
    "boot": "/api/boot",
    "layout": "/api/layout",
    "provenance": "/api/provenance",
    "lint": "/api/lint",
    "saves": "/api/saves",
    "canon": "/api/canon",
    "convert": "/api/convert",
    "blank": "/api/blank",
    "build": "/api/build",
    "card": "/api/card",
    "split": "/api/split",
    "join": "/api/join",
    "merge": "/api/merge",
    "unmerge": "/api/unmerge",
    "export": "/api/export",
    "import-ares": "/api/import-ares",
    "extract": "/api/extract",
    "insert": "/api/insert",
    "set": "/api/set",
    "clean": "/api/clean",
    "rebuild": "/api/rebuild",
    "patch": "/api/patch",
    "save-apply": "/api/save-apply",
    "save-extract": "/api/save-extract",
    "normalise-saves": "/api/normalise-saves",
    "splice": "/api/splice",
    "consensus": "/api/consensus",
    "masters": "/api/masters",
    "reference-build": "/api/reference-build",
    "reference-verify": "/api/reference-verify",
    "dat-build": "/api/dat-build",
    "identify": "/api/identify",
    "bios": "/api/bios",
    "dat-cache": "/api/dat-cache",
    "integrity": "/api/integrity",
    "calibrate": "/api/calibrate",
    "grade": "/api/grade",
    "reads": "/api/reads",
    "flux": "/api/flux",
    "flux-decode": "/api/flux-decode",
    "classes": "/api/classes",
    "tune": "/api/tune",
    "tune-sweep": "/api/tune-sweep",
    "reading": "/api/reading",
    "dump": "/api/dump",
    "write": "/api/write",
    "surface": "/api/surface",
}


def _bytes_of(encoded: str) -> bytes:
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        message = f"the payload is not base64: {error}"
        raise HTTPException(status_code=BAD_REQUEST, detail=message) from error
    if not data:
        message = "the payload carries no bytes"
        raise HTTPException(status_code=BAD_REQUEST, detail=message)
    return data


def _decode(encoded: str) -> tuple[Disk, bytes, tuple[Diagnostic, ...]]:
    data = _bytes_of(encoded)
    try:
        reject_foreign(data)
    except ForeignImageError as error:
        raise HTTPException(status_code=BAD_REQUEST, detail=str(error)) from error
    disk, findings = fds.decode(data)
    return disk, data, findings


def _profile(name: str) -> MaskProfile:
    try:
        return profile_by_name(name)
    except (KeyError, ValueError) as error:
        message = f"there is no identity profile called {name}"
        raise HTTPException(status_code=BAD_REQUEST, detail=message) from error


def _capture(spec: CaptureSpec) -> tuple[FluxCapture, str]:
    data = _bytes_of(spec.data)
    try:
        fmt = CaptureFormat(spec.fmt) if spec.fmt else detect_format(data)
        return load_capture(data, fmt=fmt), str(fmt)
    except (ValueError, IndexError, KeyError) as error:
        message = f"this capture could not be read: {error}"
        raise HTTPException(status_code=BAD_REQUEST, detail=message) from error


def index() -> HTMLResponse:
    markup = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    stamped = markup.replace("/static/", f"{ASSET_ROOT}/")
    return HTMLResponse(stamped, headers={"cache-control": "no-store"})


def catalogue() -> Catalogue:
    return Catalogue(
        version=VERSION,
        profiles=[ProfileView.of(name) for name in sorted(PROFILES)],
        capture_formats=sorted(str(fmt) for fmt in CaptureFormat),
        export_targets=list(EXPORT_TARGETS),
        commands=sorted(ROUTE_FOR_COMMAND),
        forms=[entry.model_dump() for entry in forms()],
    )


def doctor() -> DoctorResult:
    report = diagnose()
    return DoctorResult(
        checks=[
            DoctorCheck(name=check.name, status=str(check.status), detail=check.detail)
            for check in report.checks
        ],
        healthy=report.healthy,
    )


def hardware() -> HardwareResult:
    found = next(check for check in diagnose().checks if check.name == DEVICE_CHECK)
    return HardwareResult(connected=found.status is CheckStatus.OK, detail=found.detail)


def info(spec: ImageSpec) -> DiskView:
    disk, _, _ = _decode(spec.data)
    return DiskView.of(disk)


def verify(spec: VerifySpec) -> VerifyResult:
    _, _, findings = _decode(spec.data)
    worst = worst_severity(findings)
    ok = not findings if spec.strict else str(worst) != "error"
    return VerifyResult(
        ok=ok,
        worst_severity=str(worst),
        diagnostics=[DiagnosticView.of(finding) for finding in findings],
    )


def hashes(spec: HashSpec) -> HashResult:
    disk, data, _ = _decode(spec.data)
    canonical = canonicalise(disk, _profile(spec.profile))
    return HashResult(
        whole=DigestView.of(digests_of(data)),
        sides=[DigestView.of(entry) for entry in side_digests(data, SIDE_SIZE)],
        canonical=digest_string(canonical),
        retroachievements=retroachievements_hash(data),
    )


def grade(spec: GradeSpec) -> GradeResult:
    disk, _, findings = _decode(spec.data)
    others = [_decode(entry)[0] for entry in spec.reads]
    stats = compare_reads([disk, *others]) if others else None
    confidence = score_disk(disk, reads=stats, margin=spec.margin)
    return GradeResult.of(grade_disk(confidence=confidence, findings=findings, reads=stats))


def reads(spec: ReadsSpec) -> ReadsResult:
    if len(spec.images) < MIN_READS:
        message = "comparing reads needs at least two dumps of the same disk"
        raise HTTPException(status_code=UNPROCESSABLE, detail=message)
    disks = [_decode(entry)[0] for entry in spec.images]
    return ReadsResult.of(compare_reads(disks))


def flux(spec: CaptureSpec) -> FluxResult:
    capture, fmt = _capture(spec)
    return FluxResult.of(analyse_capture(capture), fmt)


def tune(spec: CaptureSpec) -> TuneResult:
    capture, _ = _capture(spec)
    if capture.quantised:
        message = (
            "this capture carries pulse classes rather than timing, so it cannot "
            "measure speed. Use the classes endpoint instead"
        )
        raise HTTPException(status_code=UNPROCESSABLE, detail=message)
    return TuneResult.of(advise(capture.track(0).intervals()))


def reading(spec: CyclesSpec) -> SpeedView:
    return SpeedView.of(from_cycles(spec.cycles))


def classes(spec: CaptureSpec) -> ClassesResult:
    data = _bytes_of(spec.data)
    return ClassesResult.of(measure_classes(data, packed=(spec.fmt or "raw03") == "raw03"))


def blank(spec: BlankSpec) -> FileResult:
    data = blank_image(
        sides=spec.sides,
        headered=spec.headered,
        formatted=spec.formatted,
        game_name=spec.game_name,
    )
    return FileResult(
        name="blank.fds",
        data=base64.b64encode(data).decode("ascii"),
        size=len(data),
    )


def canon(spec: CanonSpec) -> FileResult:
    disk, _, _ = _decode(spec.data)
    canonical = canonicalise(disk, _profile(spec.profile))
    data = restore(canonical)
    return FileResult(
        name=f"{Path(spec.name).stem}.{spec.profile}.fds",
        data=base64.b64encode(data).decode("ascii"),
        size=len(data),
    )


def convert(spec: ConvertSpec) -> FileResult:
    disk, _, _ = _decode(spec.data)
    stem = Path(spec.name).stem
    if spec.to_qd:
        body, _ = qd.encode(disk, crc_mode=CrcMode.PRESERVE)
        return FileResult(
            name=f"{stem}.qd",
            data=base64.b64encode(body).decode("ascii"),
            size=len(body),
        )
    body, _ = fds.encode(disk, headered=spec.headered)
    return FileResult(
        name=f"{stem}.fds",
        data=base64.b64encode(body).decode("ascii"),
        size=len(body),
    )


def _register_core(app: FastAPI) -> None:
    app.add_api_route("/", index, methods=["GET"], response_class=HTMLResponse)
    app.add_api_route("/api/catalogue", catalogue, methods=["GET"])
    app.add_api_route("/api/doctor", doctor, methods=["GET"])
    app.add_api_route("/api/hardware", hardware, methods=["GET"])
    app.add_api_route("/api/info", info, methods=["POST"])
    app.add_api_route("/api/verify", verify, methods=["POST"])
    app.add_api_route("/api/hash", hashes, methods=["POST"])
    app.add_api_route("/api/grade", grade, methods=["POST"])
    app.add_api_route("/api/reads", reads, methods=["POST"])
    app.add_api_route("/api/flux", flux, methods=["POST"])
    app.add_api_route("/api/tune", tune, methods=["POST"])
    app.add_api_route("/api/reading", reading, methods=["POST"])
    app.add_api_route("/api/classes", classes, methods=["POST"])
    app.add_api_route("/api/blank", blank, methods=["POST"])
    app.add_api_route("/api/canon", canon, methods=["POST"])
    app.add_api_route("/api/convert", convert, methods=["POST"])


def _register_image(app: FastAPI) -> None:
    app.add_api_route("/api/ls", image_routes.ls, methods=["POST"])
    app.add_api_route("/api/diff", image_routes.diff, methods=["POST"])
    app.add_api_route("/api/boot", image_routes.boot, methods=["POST"])
    app.add_api_route("/api/layout", image_routes.layout, methods=["POST"])
    app.add_api_route("/api/provenance", image_routes.provenance, methods=["POST"])
    app.add_api_route("/api/lint", image_routes.lint, methods=["POST"])
    app.add_api_route("/api/saves", image_routes.saves, methods=["POST"])
    app.add_api_route("/api/extract", image_routes.extract, methods=["POST"])
    app.add_api_route("/api/insert", image_routes.insert, methods=["POST"])
    app.add_api_route("/api/set", image_routes.edit, methods=["POST"])
    app.add_api_route("/api/clean", image_routes.clean, methods=["POST"])
    app.add_api_route("/api/rebuild", image_routes.rebuild_image, methods=["POST"])
    app.add_api_route("/api/patch", image_routes.patch, methods=["POST"])
    app.add_api_route("/api/save-apply", image_routes.save_apply, methods=["POST"])
    app.add_api_route("/api/save-extract", image_routes.save_extract, methods=["POST"])
    app.add_api_route("/api/normalise-saves", image_routes.normalise, methods=["POST"])
    app.add_api_route("/api/split", image_routes.split, methods=["POST"])
    app.add_api_route("/api/join", image_routes.join, methods=["POST"])
    app.add_api_route("/api/merge", image_routes.merge, methods=["POST"])
    app.add_api_route("/api/unmerge", image_routes.unmerge, methods=["POST"])
    app.add_api_route("/api/export", image_routes.export, methods=["POST"])
    app.add_api_route("/api/import-ares", image_routes.import_ares, methods=["POST"])
    app.add_api_route("/api/build", image_routes.build, methods=["POST"])
    app.add_api_route("/api/card", image_routes.card, methods=["POST"])


def _register_analysis(app: FastAPI) -> None:
    app.add_api_route("/api/calibrate", analysis_routes.calibrate_drive, methods=["POST"])
    app.add_api_route("/api/integrity", analysis_routes.integrity, methods=["POST"])
    app.add_api_route("/api/splice", analysis_routes.splice_blocks, methods=["POST"])
    app.add_api_route("/api/consensus", analysis_routes.consensus, methods=["POST"])
    app.add_api_route("/api/masters", analysis_routes.masters, methods=["POST"])
    app.add_api_route("/api/reference-build", analysis_routes.reference_build, methods=["POST"])
    app.add_api_route("/api/reference-verify", analysis_routes.reference_verify, methods=["POST"])
    app.add_api_route("/api/dat-build", analysis_routes.dat_build, methods=["POST"])
    app.add_api_route("/api/identify", analysis_routes.identify, methods=["POST"])
    app.add_api_route("/api/bios", analysis_routes.bios, methods=["POST"])
    app.add_api_route("/api/dat-cache", analysis_routes.dat_cache, methods=["GET"])
    app.add_api_route("/api/flux-decode", analysis_routes.flux_decode, methods=["POST"])
    app.add_api_route("/api/tune-sweep", analysis_routes.tune_sweep, methods=["POST"])


def _register_hardware(app: FastAPI) -> None:
    app.add_api_route("/api/dump", hardware_routes.dump_route, methods=["POST"])
    app.add_api_route("/api/write", hardware_routes.write_route, methods=["POST"])
    app.add_api_route("/api/surface", hardware_routes.surface_route, methods=["POST"])


DEVICE_CHECK: Final = "fdsstick"

MAX_BODY_BYTES: Final = 64 * 1024 * 1024
TOO_LARGE: Final = 413


async def _reject_oversized(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=TOO_LARGE,
            content={
                "detail": (
                    f"the request carries {int(declared)} bytes, and this server accepts "
                    f"{MAX_BODY_BYTES} at most. A two-side disk image is about 131,000 bytes"
                )
            },
        )
    return await call_next(request)


async def _label_asset_lifetime(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    answer = await call_next(request)
    path = request.url.path
    if path.startswith(f"{ASSET_ROOT}/"):
        answer.headers["cache-control"] = f"public, max-age={A_YEAR}, immutable"
    elif path.startswith("/static/"):
        answer.headers["cache-control"] = "no-cache"
    return answer


def create_app() -> FastAPI:
    app = FastAPI(title="fdstoolkit", version=VERSION, docs_url="/docs")
    app.middleware("http")(_label_asset_lifetime)
    app.middleware("http")(_reject_oversized)
    _register_core(app)
    _register_image(app)
    _register_analysis(app)
    _register_hardware(app)
    app.mount(ASSET_ROOT, StaticFiles(directory=STATIC_DIR), name="assets")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
