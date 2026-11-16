from __future__ import annotations

import pytest
from surface_kit import DOMINANT, KEY, MIXED_SHARE, OTHER_KEY, data_of, shares

from fdstoolkit.core.blocks import BlockKind
from fdstoolkit.quality.surface_disks import PATTERNS, SurfacePattern, pattern_disk


@pytest.mark.parametrize(
    ("pattern", "position"),
    [(SurfacePattern.SHORT, 0), (SurfacePattern.MEDIUM, 1), (SurfacePattern.LONG, 2)],
)
def test_each_fixed_pattern_writes_one_pulse_class(pattern: SurfacePattern, position: int) -> None:
    # Arrange
    data = data_of(pattern)

    # Act
    found = shares(data)

    # Assert
    assert found[position] >= DOMINANT


def test_the_unique_pattern_writes_every_pulse_class() -> None:
    # Arrange
    data = data_of(SurfacePattern.UNIQUE)

    # Act
    found = shares(data)

    # Assert
    assert all(share > MIXED_SHARE for share in found)


def test_the_unique_pattern_changes_with_its_key_and_differs_between_files() -> None:
    # Arrange
    pattern = SurfacePattern.UNIQUE

    # Act
    side = pattern_disk(pattern, sides=1, key=KEY).sides[0]

    # Assert
    files = [b.payload for b in side.blocks if b.kind is BlockKind.FILE_DATA]
    assert len(set(files)) == len(files)
    assert data_of(pattern, KEY) != data_of(pattern, OTHER_KEY)


def test_every_pulse_class_is_written_in_one_pass() -> None:
    # Arrange
    expected = set(SurfacePattern)

    # Act
    result = set(PATTERNS)

    # Assert
    assert result == expected
