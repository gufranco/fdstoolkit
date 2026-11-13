from __future__ import annotations

import importlib

import pytest

import fdstoolkit
from fdstoolkit.build.blank import blank_image

MEASUREMENT_NAMES = (
    "decode_image",
    "encode_disk",
    "digests_of",
    "canonical_digest",
    "grade_disk",
    "compare_reads",
    "calibrate",
    "sample_side",
    "score_disk",
)

MODEL_NAMES = ("Disk", "Side", "Block", "BlockKind")


def test_the_version_is_published() -> None:
    # Arrange
    package = fdstoolkit

    # Act
    version = package.__version__

    # Assert
    assert version
    assert version[0].isdigit()


@pytest.mark.parametrize("name", MEASUREMENT_NAMES)
def test_every_measurement_entry_point_is_importable(name: str) -> None:
    # Arrange
    obj = getattr(fdstoolkit, name)

    # Act
    result = callable(obj)

    # Assert
    assert result


@pytest.mark.parametrize("name", MODEL_NAMES)
def test_every_model_type_is_importable(name: str) -> None:
    # Arrange
    obj = getattr(fdstoolkit, name)

    # Act
    result = isinstance(obj, type)

    # Assert
    assert result


def test_the_documented_surface_is_what_all_declares() -> None:
    # Arrange
    expected = set(fdstoolkit.__all__)

    # Act
    result = set(MEASUREMENT_NAMES)

    # Assert
    assert result <= expected
    assert set(MODEL_NAMES) <= set(fdstoolkit.__all__)


def test_everything_all_names_actually_exists() -> None:
    # Arrange
    expected = []

    # Act
    missing = [name for name in fdstoolkit.__all__ if not hasattr(fdstoolkit, name)]

    # Assert
    assert missing == expected


def test_the_measurement_path_runs_without_touching_a_cli_module() -> None:
    # Arrange
    data = blank_image(sides=1, headered=False, formatted=True, game_name="SMB")
    disk, findings = fdstoolkit.decode_image(data)

    # Act
    again = fdstoolkit.encode_disk(disk)

    # Assert
    assert again == data
    assert findings == ()


def test_a_grade_is_reachable_from_the_package_root() -> None:
    # Arrange
    data = blank_image(sides=1, headered=False, formatted=True, game_name="SMB")
    disk, findings = fdstoolkit.decode_image(data)
    confidence = fdstoolkit.score_disk(disk)

    # Act
    report = fdstoolkit.grade_disk(confidence=confidence, findings=findings)

    # Assert
    assert report.grade


def test_a_canonical_digest_is_reachable_from_the_package_root() -> None:
    # Arrange
    data = blank_image(sides=1, headered=False, formatted=True, game_name="SMB")
    disk, _ = fdstoolkit.decode_image(data)

    # Act
    digest = fdstoolkit.canonical_digest(disk, "release")

    # Assert
    assert digest.startswith("fdstoolkit:v1:release/")


def test_importing_the_package_pulls_in_no_cli_module() -> None:
    # Arrange
    name = "fdstoolkit"

    # Act
    module = importlib.import_module(name)

    # Assert
    assert not hasattr(module, "app")
    assert not hasattr(module, "typer")
