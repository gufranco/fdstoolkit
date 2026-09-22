from __future__ import annotations

import os
from pathlib import Path

import pytest

from fdstk.codecs import fds, qd
from fdstk.core.canon import canonicalise, restore
from fdstk.core.diskinfo import CONTENT_PROFILE, RAW_PROFILE

pytestmark = pytest.mark.corpus

CORPUS_ENV = "FDSTK_CORPUS"


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
