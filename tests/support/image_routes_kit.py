from __future__ import annotations

import base64
import io
import zipfile
from pathlib import Path

from fakes import game_name, seeded

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.codecs.fds import encode
from fdstoolkit.drive.captures import Capture, bundle_zip

FAKE = seeded(__name__)
GAME = game_name(FAKE)
OTHER_GAME = game_name(FAKE)

OK = 200


BAD_REQUEST = 400


UNPROCESSABLE = 422


IMAGE = blank_image(sides=2, headered=False, formatted=True, game_name=GAME)


ONE_SIDE = blank_image(sides=1, headered=False, formatted=True, game_name=GAME)


RENAMED_IMAGE = blank_image(sides=2, headered=False, formatted=True, game_name=OTHER_GAME)


ENCODED = base64.b64encode(IMAGE).decode("ascii")


ONE = base64.b64encode(ONE_SIDE).decode("ascii")


RENAMED = base64.b64encode(RENAMED_IMAGE).decode("ascii")


def written_side() -> tuple[str, str]:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "fdsstick"
    capture = Capture(side=0, read=1, data=(fixture / "calibration-side.raw03").read_bytes())
    image = encode(calibration_disk(1), headered=False)[0]
    bundle = bundle_zip([capture], image="calibration.fds", created="2026-11-13T00:00:00Z")
    return base64.b64encode(image).decode("ascii"), base64.b64encode(bundle).decode("ascii")


def ips_patch(original: bytes, changed: bytes) -> bytes:
    body = bytearray(b"PATCH")
    for offset, (was, now) in enumerate(zip(original, changed, strict=False)):
        if was != now:
            body += offset.to_bytes(3, "big") + (1).to_bytes(2, "big") + bytes([now])
    body += b"EOF"
    return bytes(body)


def zipped_folder(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()
