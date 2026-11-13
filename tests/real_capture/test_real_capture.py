from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

from fdstoolkit.build.calibration import calibration_disk
from fdstoolkit.codecs.fds import encode
from fdstoolkit.codecs.raw import block_regions, decode_packed, encode_raw03, unpack_detected
from fdstoolkit.drive.monitor import sample

FIXTURE: Final = Path(__file__).resolve().parents[1] / "fixtures" / "fdsstick"
LOST_OR_BROKEN: Final = frozenset({"FDS002", "FDS004", "FDS014", "FDS015"})


def provenance() -> dict[str, str]:
    loaded: dict[str, str] = json.loads((FIXTURE / "calibration-side.json").read_text())
    return loaded


def real_capture() -> bytes:
    return (FIXTURE / provenance()["capture"]).read_bytes()


def written_payloads() -> list[bytes]:
    return [block.payload for block in calibration_disk(1).sides[0].blocks]


def test_the_capture_is_the_one_its_provenance_names() -> None:
    # Arrange
    capture = real_capture()

    # Act
    digest = hashlib.sha256(capture).hexdigest()

    # Assert
    assert digest == provenance()["capture_sha256"]


def test_the_written_image_is_the_one_its_provenance_names() -> None:
    # Arrange
    image, _ = encode(calibration_disk(1), headered=False)

    # Act
    digest = hashlib.sha256(image).hexdigest()

    # Assert
    assert digest == provenance()["image_sha256"]


def test_a_real_read_decodes_to_every_block_that_was_written() -> None:
    # Arrange
    capture = real_capture()

    # Act
    side, _ = decode_packed(capture)

    # Assert
    assert [block.payload for block in side.blocks] == written_payloads()


def test_a_real_read_carries_no_lost_or_broken_block() -> None:
    # Arrange
    capture = real_capture()

    # Act
    _, findings = decode_packed(capture)

    # Assert
    assert {finding.code for finding in findings} & LOST_OR_BROKEN == set()


def test_the_encoder_emits_the_pulses_a_real_stick_read_for_every_block() -> None:
    # Arrange
    real = unpack_detected(real_capture())
    encoded = unpack_detected(encode_raw03(calibration_disk(1), side=0))

    # Act
    pairs = list(zip(block_regions(real), block_regions(encoded), strict=True))

    # Assert
    assert len(pairs) == len(written_payloads())
    assert all(
        real[start:end] == encoded[other_start:other_end]
        for (start, end), (other_start, other_end) in pairs
    )


def test_a_real_read_of_the_calibration_side_measures_clean_against_itself() -> None:
    # Arrange
    reference = calibration_disk(1).sides[0]

    # Act
    measured = sample(real_capture(), reference)

    # Assert
    assert (measured.short, measured.long, measured.invalid) == (0, 0, 0)
    assert all(measured.blocks)
