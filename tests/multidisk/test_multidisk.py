from __future__ import annotations

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.diagnostics import Diagnostic, Severity
from fdstoolkit.core.disk import Disk
from fdstoolkit.edit.multidisk import MAX_SIDES, merge, unmerge


def game(*, name: str = "SMB", sides: int = 2) -> Disk:
    disk, _ = decode(blank_image(sides=sides, headered=False, formatted=True, game_name=name))
    return disk


def codes(findings: tuple[Diagnostic, ...]) -> list[str]:
    return [entry.code for entry in findings]


def test_merging_two_disks_keeps_every_side_in_order() -> None:
    first, second = game(), game()

    merged, findings = merge([first, second])

    assert merged.side_count == 4
    assert merged.sides[:2] == first.sides
    assert merged.sides[2:] == second.sides
    assert findings == ()


def test_merging_one_disk_returns_it_unchanged() -> None:
    only = game()

    merged, findings = merge([only])

    assert merged.sides == only.sides
    assert findings == ()


def test_merging_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one image"):
        merge([])


def test_merging_disks_of_different_games_is_reported() -> None:
    _, findings = merge([game(name="SMB"), game(name="ZEL")])

    assert codes(findings) == ["FDS016"]


def test_merging_past_eight_sides_is_refused() -> None:
    with pytest.raises(ValueError, match=str(MAX_SIDES)):
        merge([game(sides=8), game(sides=2)])


def test_a_merged_image_declares_its_own_side_count() -> None:
    headered, _ = decode(blank_image(sides=2, headered=True, formatted=True))

    merged, _ = merge([headered, headered])

    assert merged.header_side_count == 4


def test_a_merge_of_headerless_images_stays_headerless() -> None:
    merged, _ = merge([game(), game()])

    assert merged.header_side_count is None


def test_unmerging_splits_on_the_disk_number() -> None:
    merged, _ = merge([game(), game()])

    parts, findings = unmerge(merged)

    assert [part.side_count for part in parts] == [2, 2]
    assert findings == ()


def test_unmerging_returns_the_original_disks() -> None:
    first, second = game(name="ON1"), game(name="ON2")
    merged, _ = merge([first, second])

    parts, _ = unmerge(merged)

    assert parts[0].sides == first.sides
    assert parts[1].sides == second.sides


def test_a_single_disk_unmerges_to_itself() -> None:
    parts, findings = unmerge(game())

    assert len(parts) == 1
    assert findings == ()


def test_an_unformatted_side_joins_the_part_before_it() -> None:
    blank, _ = decode(blank_image(sides=1, headered=False, formatted=False))
    mixed = Disk(sides=(*game(sides=1).sides, *blank.sides))

    parts, findings = unmerge(mixed)

    assert len(parts) == 1
    assert codes(findings) == ["FDS017"]


def test_a_leading_unformatted_side_is_its_own_part() -> None:
    blank, _ = decode(blank_image(sides=1, headered=False, formatted=False))

    parts, findings = unmerge(blank)

    assert len(parts) == 1
    assert codes(findings) == ["FDS017"]


def test_unmerging_uses_the_disk_number_rather_than_pairs() -> None:
    three = game(sides=3)

    parts, _ = unmerge(three)

    assert [part.side_count for part in parts] == [2, 1]


def test_each_part_carries_its_own_header_count_when_the_source_did() -> None:
    headered, _ = decode(blank_image(sides=4, headered=True, formatted=True))

    parts, _ = unmerge(headered)

    assert [part.header_side_count for part in parts] == [2, 2]


def test_different_game_codes_are_reported_but_not_a_warning() -> None:
    _, findings = merge([game(name="ON1"), game(name="ON2")])

    assert [entry.severity for entry in findings] == [Severity.INFO]
