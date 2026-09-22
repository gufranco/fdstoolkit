from __future__ import annotations

import pytest

from fdstoolkit.drive.bracket import Bracket, Setting, bracket_of


def _setting(label: str, rate: float, *, clean: bool, margin: float = 0.8) -> Setting:
    return Setting(label=label, bit_rate_hz=rate, margin=margin, errors=0 if clean else 3)


def test_a_setting_knows_whether_it_read_clean() -> None:
    assert _setting("a", 96_400, clean=True).clean
    assert not _setting("a", 96_400, clean=False).clean


def test_a_sweep_with_no_setting_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one setting"):
        bracket_of([])


def test_a_sweep_that_never_read_clean_has_no_window() -> None:
    sweep = bracket_of([_setting("a", 90_000, clean=False), _setting("b", 96_400, clean=False)])

    assert sweep.window is None
    assert sweep.centre is None
    assert not sweep.usable


def test_a_sweep_that_read_clean_reports_its_window() -> None:
    sweep = bracket_of(
        [
            _setting("-2", 92_000, clean=False),
            _setting("-1", 94_000, clean=True),
            _setting("0", 96_400, clean=True),
            _setting("+1", 98_500, clean=True),
            _setting("+2", 101_000, clean=False),
        ]
    )

    assert sweep.window == (94_000, 98_500)
    assert sweep.centre == pytest.approx(96_250)
    assert sweep.usable


def test_the_window_width_is_reported_as_a_share_of_nominal() -> None:
    sweep = bracket_of(
        [
            _setting("-1", 94_000, clean=True),
            _setting("0", 96_400, clean=True),
            _setting("+1", 98_500, clean=True),
        ]
    )

    assert sweep.width == pytest.approx((98_500 - 94_000) / 96_400, rel=1e-6)


def test_a_wide_window_scores_better_than_a_narrow_one() -> None:
    wide = bracket_of(
        [
            _setting("-1", 90_000, clean=True),
            _setting("0", 96_400, clean=True),
            _setting("+1", 103_000, clean=True),
        ]
    )
    narrow = bracket_of(
        [
            _setting("-1", 96_000, clean=False),
            _setting("0", 96_400, clean=True),
            _setting("+1", 96_800, clean=False),
        ]
    )

    assert wide.health > narrow.health
    assert 0.0 <= narrow.health <= 1.0


def test_a_single_clean_setting_gives_a_window_of_no_width() -> None:
    sweep = bracket_of([_setting("0", 96_400, clean=True)])

    assert sweep.window == (96_400, 96_400)
    assert sweep.centre == 96_400
    assert sweep.width == 0.0


def test_the_sweep_names_the_setting_nearest_its_centre() -> None:
    sweep = bracket_of(
        [
            _setting("-1", 94_000, clean=True),
            _setting("0", 96_400, clean=True),
            _setting("+1", 98_500, clean=True),
        ]
    )

    assert sweep.best is not None
    assert sweep.best.label == "0"


def test_a_sweep_with_no_clean_setting_names_no_best() -> None:
    assert bracket_of([_setting("a", 90_000, clean=False)]).best is None


def test_the_sweep_renders_a_line_naming_the_centre() -> None:
    sweep = bracket_of([_setting("-1", 94_000, clean=True), _setting("+1", 98_500, clean=True)])

    text = sweep.render()
    assert "96" in text
    assert "window" in text


def test_a_sweep_that_never_read_clean_says_so() -> None:
    assert "no setting" in bracket_of([_setting("a", 90_000, clean=False)]).render()


def test_settings_are_ordered_by_rate_regardless_of_input_order() -> None:
    sweep = Bracket(
        settings=(
            _setting("+1", 98_500, clean=True),
            _setting("-1", 94_000, clean=True),
        )
    )

    assert [item.bit_rate_hz for item in sweep.ordered] == [94_000, 98_500]
