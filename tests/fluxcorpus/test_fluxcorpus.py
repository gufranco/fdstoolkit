from __future__ import annotations

import os
from pathlib import Path

import pytest

from fdstoolkit.flux.analysis import analyse_intervals, fit_family
from fdstoolkit.flux.load import CaptureFormat, detect_format, load_capture
from fdstoolkit.flux.model import NOMINAL_RPM

pytestmark = pytest.mark.corpus

CORPUS_ENV = "FDSTOOLKIT_FLUX_CORPUS"
SUFFIXES = (".scp", ".raw", ".hfe")
PLAUSIBLE_RPM = (90.0, 400.0)
PLAUSIBLE_CELL_NS = (500.0, 40_000.0)


def corpus_root() -> Path:
    raw = os.environ.get(CORPUS_ENV)
    if not raw:
        pytest.skip(f"set {CORPUS_ENV} to a directory of real flux captures to run this")
    root = Path(raw).expanduser()
    if not root.is_dir():
        pytest.skip(f"{CORPUS_ENV} does not name a directory: {root}")
    return root


def captures() -> list[Path]:
    return sorted(p for p in corpus_root().rglob("*") if p.suffix.lower() in SUFFIXES)


def test_the_corpus_holds_a_capture() -> None:
    assert captures(), "the flux corpus directory holds no capture"


def test_every_capture_is_detected_and_loads() -> None:
    for path in captures():
        data = path.read_bytes()
        fmt = detect_format(data)
        assert fmt in set(CaptureFormat)
        capture = load_capture(data)
        assert capture.track_count >= 1
        assert capture.pulse_count > 0


def test_every_capture_spins_at_a_plausible_speed() -> None:
    low, high = PLAUSIBLE_RPM
    for path in captures():
        capture = load_capture(path.read_bytes())
        for track in capture.tracks:
            speeds = sorted(
                revolution.rpm
                for revolution in track.revolutions
                if revolution.complete and revolution.pulse_count >= 1_000
            )
            if not speeds:
                continue
            median = speeds[len(speeds) // 2]
            assert low <= median <= high, f"{path.name} track {track.index} at {median:.1f} rpm"


def test_the_whole_revolutions_of_a_capture_agree_on_speed() -> None:
    for path in captures():
        capture = load_capture(path.read_bytes())
        for track in capture.tracks:
            speeds = [
                revolution.rpm
                for revolution in track.revolutions
                if revolution.complete and revolution.pulse_count >= 1_000
            ]
            if len(speeds) < 2:
                continue
            assert max(speeds) - min(speeds) < max(speeds) * 0.05, path.name


def test_every_capture_fits_a_known_pulse_family() -> None:
    low, high = PLAUSIBLE_CELL_NS
    for path in captures():
        capture = load_capture(path.read_bytes())
        for track in capture.tracks:
            intervals = track.intervals(0)
            if len(intervals) < 1_000:
                continue
            base, ratios, name = fit_family(intervals)
            assert name in {"mfm", "gcr"}
            assert len(ratios) == 3
            assert low <= base <= high, f"{path.name} track {track.index} base {base}"


def test_a_preserved_capture_separates_cleanly() -> None:
    for path in captures():
        capture = load_capture(path.read_bytes())
        for track in capture.tracks:
            intervals = track.intervals(0)
            if len(intervals) < 1_000:
                continue
            report = analyse_intervals(intervals)
            assert len(report.clusters) == 3
            assert report.worst_margin > 0.3, (
                f"{path.name} track {track.index} margin {report.worst_margin:.1%}"
            )


def test_the_nominal_disk_system_speed_is_unchanged() -> None:
    assert NOMINAL_RPM == 96.0
