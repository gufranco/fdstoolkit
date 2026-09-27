from __future__ import annotations

import base64
import logging
import secrets
from collections.abc import Awaitable, Callable
from hashlib import sha256
from importlib import resources
from pathlib import Path
from typing import Final

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from fdstoolkit.build.blank import DEFAULT_GAME_NAME, blank_image
from fdstoolkit.build.calibration import DECIDES_ITSELF, calibration_image
from fdstoolkit.build.targets import TARGETS
from fdstoolkit.codecs import fds, qd
from fdstoolkit.codecs.qd import CrcMode
from fdstoolkit.core.canon import canonicalise, digest_string, profile_by_name, restore
from fdstoolkit.core.diagnostics import worst_severity
from fdstoolkit.core.disk import Disk
from fdstoolkit.core.diskinfo import PROFILES, MaskProfile
from fdstoolkit.doctor import CheckStatus, hardware_checks
from fdstoolkit.drive.captures import Bundle
from fdstoolkit.drive.pulse import bundle_findings
from fdstoolkit.drive.recovery import captures_of_another_disk
from fdstoolkit.drive.weak import bundle_weak_blocks
from fdstoolkit.identify.hashes import digests_of, retroachievements_hash, side_digests
from fdstoolkit.quality.confidence import score_disk
from fdstoolkit.quality.grade import grade_disk
from fdstoolkit.quality.reads import compare_reads
from fdstoolkit.ui import analysis_routes, hardware_routes, image_routes
from fdstoolkit.ui.body_limit import BodyLimit
from fdstoolkit.ui.forms import FAMILY_ORDER, forms
from fdstoolkit.ui.jobs import JobBoard
from fdstoolkit.ui.request_guard import request_guard
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
from fdstoolkit.ui.shared import (
    BAD_REQUEST,
    UNPROCESSABLE,
    bundle_of,
    decode_payload,
    named_file,
    refuse,
)
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
NONCE_BYTES: Final = 16
FAULT_REFERENCE_BYTES: Final = 6
PAGE_SCRIPT: Final = '<script type="module">'
PAGE_POLICY: Final = (
    "default-src 'self'; script-src 'nonce-{nonce}' 'strict-dynamic'; style-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
SIDE_SIZE: Final = fds.SIDE_SIZE
MIN_READS: Final = 2
CALIBRATION_NAME: Final = "calibration.fds"
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
    "probe": "/api/jobs/probe",
}


def _profile(name: str) -> MaskProfile:
    try:
        return profile_by_name(name)
    except (KeyError, ValueError) as error:
        message = f"there is no identity profile called {name}"
        raise HTTPException(status_code=BAD_REQUEST, detail=message) from error


def index() -> HTMLResponse:
    nonce = secrets.token_urlsafe(NONCE_BYTES)
    markup = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    stamped = markup.replace("/static/", f"{ASSET_ROOT}/").replace(
        PAGE_SCRIPT, f'<script type="module" nonce="{nonce}">'
    )
    return HTMLResponse(
        stamped,
        headers={
            "cache-control": "no-store",
            "content-security-policy": PAGE_POLICY.format(nonce=nonce),
        },
    )


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


def _weak_count(disk: Disk, bundle: Bundle) -> int:
    foreign = captures_of_another_disk(disk, bundle)
    if foreign:
        refuse(foreign, status=UNPROCESSABLE)
    return len(bundle_weak_blocks(bundle))


def grade(spec: GradeSpec) -> GradeResult:
    disk, _, findings = decode_payload(spec.data)
    others = [decode_payload(entry)[0] for entry in spec.reads]
    stats = compare_reads([disk, *others]) if others else None
    confidence = score_disk(disk, reads=stats)
    bundle = None if spec.captures is None else bundle_of(spec.captures)
    weak = None if bundle is None else _weak_count(disk, bundle)
    pulse = () if bundle is None else bundle_findings(bundle.captures)
    return GradeResult.of(
        grade_disk(
            confidence=confidence, findings=(*findings, *pulse), reads=stats, weak_blocks=weak
        )
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
    if spec.calibration:
        if (spec.sides, spec.formatted, spec.game_name) != (1, False, DEFAULT_GAME_NAME):
            raise HTTPException(status_code=UNPROCESSABLE, detail=DECIDES_ITSELF)
        return named_file(CALIBRATION_NAME, calibration_image(headered=spec.headered))
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
    app.add_api_route("/api/jobs/probe", hardware_routes.probe_job, methods=["POST"])
    app.add_api_route("/api/jobs/current", hardware_routes.current_job, methods=["GET"])
    app.add_api_route("/api/jobs/{job_id}", hardware_routes.job_status, methods=["GET"])
    app.add_api_route("/api/jobs/{job_id}/answer", hardware_routes.job_answer, methods=["POST"])
    app.add_api_route("/api/jobs/{job_id}/stop", hardware_routes.job_stop, methods=["POST"])


DEVICE_CHECK: Final = "fdsstick"
SERVER_FAULT: Final = 500

logger = logging.getLogger("uvicorn.error")

MAX_BODY_BYTES: Final = 64 * 1024 * 1024


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
    reference = secrets.token_hex(FAULT_REFERENCE_BYTES)
    logger.error(
        "%s %s failed, reference %s", request.method, request.url.path, reference, exc_info=error
    )
    return JSONResponse(
        status_code=SERVER_FAULT,
        content={
            "detail": (
                f"the server failed on this request, reference {reference}. The full "
                "traceback is in the terminal that started fdstoolkit web, under that reference"
            )
        },
    )


def create_app(*, allowed_hosts: frozenset[str] = frozenset()) -> FastAPI:
    app = FastAPI(
        title="Famicom Disk System Toolkit",
        version=VERSION,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_exception_handler(Exception, _report_fault)
    app.state.jobs = JobBoard()
    app.middleware("http")(_label_asset_lifetime)
    app.add_middleware(BodyLimit, limit=MAX_BODY_BYTES)
    app.middleware("http")(request_guard(allowed_hosts))
    _register_core(app)
    _register_image(app)
    _register_analysis(app)
    _register_hardware(app)
    app.mount(ASSET_ROOT, StaticFiles(directory=STATIC_DIR), name="assets")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
