from __future__ import annotations

import pytest

from fdstoolkit.build.blank import blank_image
from fdstoolkit.codecs.fds import SIDE_SIZE
from fdstoolkit.codecs.mgd1 import (
    MGD1_SUFFIXES,
    SideFile,
    join_side_files,
    side_suffix_for,
    split_into_side_files,
)


def side_bytes() -> bytes:
    return blank_image(sides=1, headered=False, formatted=True, game_name="SMB")


def test_a_side_letter_is_assigned_per_index() -> None:
    assert side_suffix_for(0) == ".A"
    assert side_suffix_for(1) == ".B"
    assert side_suffix_for(3) == ".D"


def test_a_side_index_beyond_the_alphabet_is_refused() -> None:
    with pytest.raises(ValueError, match="side 8"):
        side_suffix_for(8)


def test_the_known_suffixes_cover_eight_sides() -> None:
    assert len(MGD1_SUFFIXES) == 8


def test_splitting_writes_one_file_per_side() -> None:
    files = split_into_side_files(side_bytes() * 2, stem="fc1234")

    assert [entry.name for entry in files] == ["fc1234.A", "fc1234.B"]
    assert all(len(entry.data) == SIDE_SIZE for entry in files)


def test_joining_restores_the_image() -> None:
    original = side_bytes() * 2

    assert join_side_files(split_into_side_files(original, stem="fc1234")) == original


def test_joining_sorts_by_side_letter_rather_than_by_argument_order() -> None:
    files = split_into_side_files(side_bytes() * 2, stem="fc1234")

    assert join_side_files([files[1], files[0]]) == side_bytes() * 2


def test_joining_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one side"):
        join_side_files([])


def test_a_file_whose_name_carries_no_side_letter_is_refused() -> None:
    with pytest.raises(ValueError, match="side letter"):
        join_side_files([SideFile(name="fc1234.zzz", data=side_bytes())])


def test_a_duplicate_side_letter_is_refused() -> None:
    entry = SideFile(name="fc1234.A", data=side_bytes())

    with pytest.raises(ValueError, match="twice"):
        join_side_files([entry, entry])


def test_an_oversized_side_is_kept_whole() -> None:
    oversized = side_bytes() + bytes(684)

    files = split_into_side_files(oversized, stem="gd")

    assert len(files) == 2
    assert len(files[1].data) == 684


def test_a_game_doctor_side_keeps_its_own_length_on_the_way_back() -> None:
    oversized = side_bytes() + bytes(684)

    assert join_side_files(split_into_side_files(oversized, stem="gd")) == oversized
