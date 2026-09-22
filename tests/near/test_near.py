from __future__ import annotations

from pathlib import Path

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import build_header
from fdstoolkit.identify.near import NEAR_THRESHOLD, byte_diff, nearest_match, reference_images


def blank(*, headered: bool = False, game_name: str = "SMB") -> bytes:
    return blank_image(sides=1, headered=headered, formatted=True, game_name=game_name)


def test_two_identical_images_differ_in_nothing() -> None:
    diff = byte_diff(blank(), blank())

    assert diff.differing_bytes == 0
    assert diff.first_offset is None
    assert diff.ratio == 0.0


def test_a_single_changed_byte_names_its_offset() -> None:
    other = bytearray(blank())
    other[0x34] = 0x03

    diff = byte_diff(blank(), bytes(other))

    assert diff.differing_bytes == 1
    assert diff.first_offset == 0x34
    assert diff.last_offset == 0x34


def test_a_size_difference_counts_the_missing_tail() -> None:
    diff = byte_diff(blank(), blank()[:-4])

    assert diff.differing_bytes == 4
    assert diff.sizes == (65500, 65496)


def test_differing_runs_are_grouped() -> None:
    other = bytearray(blank())
    other[0x10] = 0x5A
    other[0x34] = 0x03
    other[0x35] = 0x01

    diff = byte_diff(blank(), bytes(other))

    assert diff.runs == ((0x10, 1), (0x34, 2))


def test_the_run_list_is_capped() -> None:
    other = bytearray(blank())
    for offset in range(0, 200, 2):
        other[offset] ^= 0xFF

    diff = byte_diff(blank(), bytes(other), max_runs=3)

    assert len(diff.runs) == 3
    assert diff.truncated_runs


def test_a_header_is_stripped_before_comparing() -> None:
    diff = byte_diff(build_header(1) + blank(), blank())

    assert diff.differing_bytes == 0


def test_the_nearest_candidate_is_the_one_with_fewest_differences(tmp_path: Path) -> None:
    close = bytearray(blank())
    close[0x34] = 0x03
    (tmp_path / "close.fds").write_bytes(bytes(close))
    (tmp_path / "far.fds").write_bytes(blank(game_name="ZEL"))

    match = nearest_match(blank(), reference_images(tmp_path))

    assert match is not None
    assert match.path.name == "close.fds"
    assert match.near


def test_a_candidate_past_the_threshold_is_not_a_near_match(tmp_path: Path) -> None:
    other = bytearray(blank())
    for offset in range(40000):
        other[offset] ^= 0xFF
    (tmp_path / "other.fds").write_bytes(bytes(other))

    match = nearest_match(blank(), reference_images(tmp_path))

    assert match is not None
    assert not match.near
    assert match.diff.ratio > NEAR_THRESHOLD


def test_an_empty_reference_directory_yields_no_match(tmp_path: Path) -> None:
    assert nearest_match(blank(), reference_images(tmp_path)) is None


def test_the_image_itself_is_skipped(tmp_path: Path) -> None:
    target = tmp_path / "same.fds"
    target.write_bytes(blank())

    assert nearest_match(blank(), reference_images(tmp_path, skip=target)) is None


def test_only_disk_images_are_considered(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_bytes(blank())

    assert list(reference_images(tmp_path)) == []


def test_an_unreadable_candidate_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "broken.fds").mkdir()

    assert nearest_match(blank(), reference_images(tmp_path)) is None


def test_a_missing_reference_directory_yields_nothing(tmp_path: Path) -> None:
    assert list(reference_images(tmp_path / "absent")) == []
