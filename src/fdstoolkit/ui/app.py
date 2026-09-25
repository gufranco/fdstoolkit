from __future__ import annotations

import base64
import logging
from collections.abc import Awaitable, Callable
from hashlib import sha256
from importlib import resources
from pathlib import Path
from typing import Final

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.targets import TARGETS
from fdstoolkit.codecs import fds, qd
from fdstoolkit.codecs.qd import CrcMode
from fdstoolkit.core.canon import canonicalise, digest_string, profile_by_name, restore
from fdstoolkit.core.diagnostics import worst_severity
from fdstoolkit.core.diskinfo import PROFILES, MaskProfile
from fdstoolkit.doctor import CheckStatus, hardware_checks
from fdstoolkit.drive.weak import bundle_weak_blocks
from fdstoolkit.identify.hashes import digests_of, retroachievements_hash, side_digests
from fdstoolkit.quality.confidence import score_disk
from fdstoolkit.quality.grade import grade_disk
from fdstoolkit.quality.reads import compare_reads
from fdstoolkit.ui import analysis_routes, hardware_routes, image_routes
from fdstoolkit.ui.forms import FAMILY_ORDER, forms
from fdstoolkit.ui.jobs import JobBoard
from fdstoolkit.ui.schemas import (
    BlankSpec,
    Catalogue,
    ConvertSpec,
    DiagnosticView,
    DigestView,
    DiskView,
    DoctorCheck,
    DoctorResult,
    FileResult,
    GradeResult,
    GradeSpec,
    HardwareResult,
    HashResult,
    HashSpec,
    ImageSpec,
    ProfileView,
    ReadsResult,
    ReadsSpec,
    VerifyResult,
    VerifySpec,
    WeakResult,
    WeakView,
)
from fdstoolkit.ui.shared import BAD_REQUEST, UNPROCESSABLE, bundle_of, decode_payload, named_file
from fdstoolkit.version import VERSION

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
EXPORT_TARGETS: Final = tuple(TARGETS)

ROUTE_FOR_COMMAND: Final[dict[str, str]] = {
    "status": "/api/status",
    "info": "/api/info",
    "verify": "/api/verify",
    "hash": "/api/hash",
    "diff": "/api/diff",
    "boot": "/api/boot",
    "provenance": "/api/provenance",
    "convert": "/api/convert",
    "blank": "/api/blank",
    "build": "/api/build",
    "export": "/api/export",
    "extract": "/api/extract",
    "insert": "/api/insert",
    "set": "/api/set",
    "rebuild": "/api/rebuild",
    "patch": "/api/patch",
    "save": "/api/save",
    "splice": "/api/splice",
    "consensus": "/api/consensus",
    "grade": "/api/grade",
    "reads": "/api/reads",
    "calibrate": "/api/jobs/calibrate",
    "dump": "/api/jobs/dump",
    "write": "/api/jobs/write",
    "surface": "/api/jobs/surface",
}


def _profile(name: str) -> MaskProfile:
    try:
        return profile_by_name(name)
    except (KeyError, ValueError) as error:
        message = f"there is no identity profile called {name}"
        raise HTTPException(status_code=BAD_REQUEST, detail=message) from error


def index() -> HTMLResponse:
    markup = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    stamped = markup.replace("/static/", f"{ASSET_ROOT}/")
    return HTMLResponse(stamped, headers={"cache-control": "no-store"})


def catalogue() -> Catalogue:
    return Catalogue(
        version=VERSION,
        profiles=[ProfileView.of(name) for name in sorted(PROFILES)],
        export_targets=list(EXPORT_TARGETS),
        commands=sorted(ROUTE_FOR_COMMAND),
        forms=[entry.model_dump() for entry in forms()],
        families=list(FAMILY_ORDER),
    )


def hardware() -> HardwareResult:
    found = next(check for check in hardware_checks() if check.name == DEVICE_CHECK)
    return HardwareResult(connected=found.status is CheckStatus.OK, detail=found.detail)


def status() -> DoctorResult:
    checks = hardware_checks()
    return DoctorResult(
        checks=[
            DoctorCheck(name=check.name, status=str(check.status), detail=check.detail)
            for check in checks
        ],
        healthy=all(check.status is CheckStatus.OK for check in checks),
    )


def info(spec: ImageSpec) -> DiskView:
    disk, _, _ = decode_payload(spec.data)
    return DiskView.of(disk)


def verify(spec: VerifySpec) -> VerifyResult:
    _, _, findings = decode_payload(spec.data)
    worst = worst_severity(findings)
    ok = not findings if spec.strict else str(worst) != "error"
    return VerifyResult(
        ok=ok,
        worst_severity=str(worst),
        diagnostics=[DiagnosticView.of(finding) for finding in findings],
    )


def hashes(spec: HashSpec) -> HashResult:
    disk, data, _ = decode_payload(spec.data)
    canonical = canonicalise(disk, _profile(spec.profile))
    image = (
        named_file(f"{Path(spec.name).stem}.{spec.profile}.fds", restore(canonical))
        if spec.canonical_image
        else None
    )
    return HashResult(
        whole=DigestView.of(digests_of(data)),
        sides=[DigestView.of(entry) for entry in side_digests(data, SIDE_SIZE)],
        canonical=digest_string(canonical),
        retroachievements=retroachievements_hash(data),
        file=image,
    )


def grade(spec: GradeSpec) -> GradeResult:
    disk, _, findings = decode_payload(spec.data)
    others = [decode_payload(entry)[0] for entry in spec.reads]
    stats = compare_reads([disk, *others]) if others else None
    confidence = score_disk(disk, reads=stats)
    weak = None if spec.captures is None else len(bundle_weak_blocks(bundle_of(spec.captures)))
    return GradeResult.of(
        grade_disk(confidence=confidence, findings=findings, reads=stats, weak_blocks=weak)
    )


def weak_result(payload: str) -> WeakResult:
    bundle = bundle_of(payload)
    return WeakResult(
        reads=len(bundle.captures),
        weak=[
            WeakView(
                side=side,
                block=entry.block,
                kind=entry.kind,
                unstable=entry.unstable,
                invalid=entry.invalid,
                reads=entry.reads,
                missing=entry.missing,
            )
            for side, entry in bundle_weak_blocks(bundle)
        ],
    )


def reads(spec: ReadsSpec) -> ReadsResult | WeakResult:
    if spec.captures is not None:
        return weak_result(spec.captures)
    if len(spec.images) < MIN_READS:
        message = "comparing reads needs at least two dumps of the same disk"
        raise HTTPException(status_code=UNPROCESSABLE, detail=message)
    disks = [decode_payload(entry)[0] for entry in spec.images]
    return ReadsResult.of(compare_reads(disks))


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


def convert(spec: ConvertSpec) -> FileResult:
    disk, _, _ = decode_payload(spec.data)
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
    app.add_api_route("/api/hardware", hardware, methods=["GET"])
    app.add_api_route("/api/status", status, methods=["GET"])
    app.add_api_route("/api/info", info, methods=["POST"])
    app.add_api_route("/api/verify", verify, methods=["POST"])
    app.add_api_route("/api/hash", hashes, methods=["POST"])
    app.add_api_route("/api/grade", grade, methods=["POST"])
    app.add_api_route("/api/reads", reads, methods=["POST"])
    app.add_api_route("/api/blank", blank, methods=["POST"])
    app.add_api_route("/api/convert", convert, methods=["POST"])


def _register_image(app: FastAPI) -> None:
    app.add_api_route("/api/diff", image_routes.diff, methods=["POST"])
    app.add_api_route("/api/boot", image_routes.boot, methods=["POST"])
    app.add_api_route("/api/provenance", image_routes.provenance, methods=["POST"])
    app.add_api_route("/api/extract", image_routes.extract, methods=["POST"])
    app.add_api_route("/api/insert", image_routes.insert, methods=["POST"])
    app.add_api_route("/api/set", image_routes.edit, methods=["POST"])
    app.add_api_route("/api/rebuild", image_routes.rebuild_image, methods=["POST"])
    app.add_api_route("/api/patch", image_routes.patch, methods=["POST"])
    app.add_api_route("/api/save", image_routes.save, methods=["POST"])
    app.add_api_route("/api/export", image_routes.export, methods=["POST"])
    app.add_api_route("/api/build", image_routes.build, methods=["POST"])


def _register_analysis(app: FastAPI) -> None:
    app.add_api_route("/api/splice", analysis_routes.splice_blocks, methods=["POST"])
    app.add_api_route("/api/consensus", analysis_routes.consensus, methods=["POST"])


def _register_hardware(app: FastAPI) -> None:
    app.add_api_route("/api/jobs/dump", hardware_routes.dump_job, methods=["POST"])
    app.add_api_route("/api/jobs/write", hardware_routes.write_job, methods=["POST"])
    app.add_api_route("/api/jobs/surface", hardware_routes.surface_job, methods=["POST"])
    app.add_api_route("/api/jobs/calibrate", hardware_routes.calibrate_job, methods=["POST"])
    app.add_api_route("/api/jobs/current", hardware_routes.current_job, methods=["GET"])
    app.add_api_route("/api/jobs/{job_id}", hardware_routes.job_status, methods=["GET"])
    app.add_api_route("/api/jobs/{job_id}/answer", hardware_routes.job_answer, methods=["POST"])
    app.add_api_route("/api/jobs/{job_id}/stop", hardware_routes.job_stop, methods=["POST"])


DEVICE_CHECK: Final = "fdsstick"
SERVER_FAULT: Final = 500

logger = logging.getLogger("uvicorn.error")

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


async def _report_fault(request: Request, error: Exception) -> JSONResponse:
    logger.error("%s %s failed", request.method, request.url.path, exc_info=error)
    return JSONResponse(
        status_code=SERVER_FAULT,
        content={
            "detail": (
                f"the server failed on this request: {type(error).__name__}: {error}. "
                "The full traceback is in the terminal that started fdstoolkit web"
            )
        },
    )


def create_app() -> FastAPI:
    app = FastAPI(title="Famicom Disk System Toolkit", version=VERSION, docs_url="/docs")
    app.add_exception_handler(Exception, _report_fault)
    app.state.jobs = JobBoard()
    app.middleware("http")(_label_asset_lifetime)
    app.middleware("http")(_reject_oversized)
    _register_core(app)
    _register_image(app)
    _register_analysis(app)
    _register_hardware(app)
    app.mount(ASSET_ROOT, StaticFiles(directory=STATIC_DIR), name="assets")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
