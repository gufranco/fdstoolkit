from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from fdstoolkit.codecs import fds, qd
from fdstoolkit.core.canon import canonicalise, restore
from fdstoolkit.core.disk import Disk
from fdstoolkit.core.diskinfo import CONTENT_PROFILE, DISK_INFO_FIELDS, RAW_PROFILE, mask_disk_info

pytestmark = pytest.mark.corpus

CORPUS_ENV = "FDSTOOLKIT_CORPUS"


def corpus_root() -> Path:
    raw = os.environ.get(CORPUS_ENV)
    if not raw:
        pytest.skip(f"set {CORPUS_ENV} to a directory of .fds and .qd images to run this")
    root = Path(raw).expanduser()
    if not root.is_dir():
        pytest.skip(f"{CORPUS_ENV} does not name a directory: {root}")
    return root


def images(suffix: str) -> list[Path]:
    found = sorted(path for path in corpus_root().rglob(f"*{suffix}") if path.is_file())
    if not found:
        pytest.skip(f"no {suffix} images under {corpus_root()}")
    return found


@pytest.fixture(scope="module")
def fds_images() -> list[Path]:
    return images(".fds")


@pytest.fixture(scope="module")
def qd_images() -> list[Path]:
    return images(".qd")


def test_every_fds_image_round_trips_byte_for_byte(fds_images: list[Path]) -> None:
    failures: list[str] = []
    for path in fds_images:
        original = path.read_bytes()
        disk, _ = fds.decode(original)
        rebuilt, _ = fds.encode(disk, headered=fds.has_header(original))
        if rebuilt != original:
            failures.append(str(path))

    assert failures == []


def test_every_qd_image_round_trips_byte_for_byte(qd_images: list[Path]) -> None:
    failures: list[str] = []
    for path in qd_images:
        original = path.read_bytes()
        disk, _ = qd.decode(original)
        rebuilt, _ = qd.encode(disk)
        if rebuilt != original:
            failures.append(str(path))

    assert failures == []


def test_canonicalisation_is_reversible_for_every_image(
    fds_images: list[Path],
    qd_images: list[Path],
) -> None:
    failures: list[str] = []
    for path in fds_images + qd_images:
        original = path.read_bytes()
        decoder = fds.decode if path.suffix.lower() == ".fds" else qd.decode
        disk, _ = decoder(original)
        result = canonicalise(disk, CONTENT_PROFILE)
        if restore(result) != original:
            failures.append(str(path))

    assert failures == []


def test_canonicalisation_is_idempotent_for_every_image(fds_images: list[Path]) -> None:
    failures: list[str] = []
    for path in fds_images:
        disk, _ = fds.decode(path.read_bytes())
        once = canonicalise(disk, CONTENT_PROFILE)
        twice = canonicalise(fds.decode(once.data)[0], CONTENT_PROFILE)
        if once.data != twice.data:
            failures.append(str(path))

    assert failures == []


def test_the_raw_profile_never_alters_an_image(fds_images: list[Path]) -> None:
    failures: list[str] = []
    for path in fds_images:
        original = path.read_bytes()
        disk, _ = fds.decode(original)
        if canonicalise(disk, RAW_PROFILE).data != original:
            failures.append(str(path))

    assert failures == []


def test_two_runs_over_the_corpus_produce_the_same_digests(fds_images: list[Path]) -> None:
    def digests() -> list[str]:
        return [
            canonicalise(fds.decode(path.read_bytes())[0], CONTENT_PROFILE).sha256
            for path in fds_images
        ]

    assert digests() == digests()


def test_masking_touches_only_the_fields_it_declares(fds_images: list[Path]) -> None:
    masked_ranges = [
        (field.offset, field.offset + field.length)
        for field in DISK_INFO_FIELDS
        if field.provenance
    ]
    offenders: list[str] = []

    for path in fds_images[:200]:
        disk, _ = fds.decode(path.read_bytes())
        for index, side in enumerate(disk.sides):
            if not side.is_formatted:
                continue
            original = side.blocks[0].payload
            masked = mask_disk_info(original, CONTENT_PROFILE)
            for offset, (left, right) in enumerate(zip(original, masked, strict=True)):
                if left == right:
                    continue
                if not any(start <= offset < stop for start, stop in masked_ranges):
                    offenders.append(f"{path.name} side {index} offset {offset:#04x}")

    assert offenders == []


def test_the_content_profile_merges_dumps_the_raw_bytes_keep_apart(
    fds_images: list[Path],
) -> None:
    raw_digests: set[bytes] = set()
    content_digests: set[bytes] = set()

    for path in fds_images[:400]:
        disk, _ = fds.decode(path.read_bytes())
        for side in disk.sides:
            if not side.is_formatted:
                continue
            one_side = Disk(sides=(side,))
            raw_digests.add(canonicalise(one_side, RAW_PROFILE).data)
            content_digests.add(canonicalise(one_side, CONTENT_PROFILE).data)

    assert len(content_digests) < len(raw_digests)


def test_the_canonical_digest_does_not_depend_on_the_environment(fds_images: list[Path]) -> None:
    sample = [str(path) for path in fds_images[:25]]
    script = (
        "import sys;"
        "from fdstoolkit.codecs import fds;"
        "from fdstoolkit.core.canon import canonicalise;"
        "from fdstoolkit.core.diskinfo import CONTENT_PROFILE;"
        "print('\\n'.join("
        "canonicalise(fds.decode(open(path,'rb').read())[0], CONTENT_PROFILE).sha256"
        " for path in sys.argv[1:]))"
    )

    def run(env: dict[str, str]) -> str:
        return subprocess.run(
            [sys.executable, "-c", script, *sample],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, **env},
        ).stdout

    first = run({"TZ": "UTC", "LANG": "C", "PYTHONHASHSEED": "0"})
    second = run({"TZ": "Pacific/Kiritimati", "LANG": "pt_BR.UTF-8", "PYTHONHASHSEED": "12345"})

    assert first == second
