from __future__ import annotations

from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from fdstoolkit.cli.common import decode_image
from fdstoolkit.cli.main import app
from fdstoolkit.codecs import fds
from fdstoolkit.core.blocks import Block, BlockKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.flux.analysis import IntervalReport, TrackReport, analyse_capture, analyse_intervals
from fdstoolkit.flux.counts import write_counts
from fdstoolkit.flux.model import FluxCapture, FluxTrack, Revolution
from fdstoolkit.flux.synth import synthesise
from fdstoolkit.identify.datfile import build_dat
from fdstoolkit.identify.integrity import CodeReport
from fdstoolkit.master.corpus import GameKey, GroupMaster, build_masters
from fdstoolkit.master.reference import ReferenceSet, reference_from
from fdstoolkit.quality.calibrate import DriveProfile
from fdstoolkit.quality.confidence import ConfidenceReport, score_disk
from fdstoolkit.quality.grade import grade_disk
from fdstoolkit.quality.reads import ReadStatistics

runner = CliRunner()


def _payload(*, licensee: int = 0) -> bytes:
    payload = bytearray(56)
    payload[0x00] = BlockKind.DISK_INFO
    payload[0x01:0x0F] = b"*NINTENDO-HVC*"
    payload[0x0F] = licensee
    payload[0x10:0x13] = b"ABC"
    return bytes(payload)


def _disk(*, licensee: int = 0) -> Disk:
    return Disk(
        sides=(
            Side(
                blocks=(Block(kind=BlockKind.DISK_INFO, payload=_payload(licensee=licensee)),),
                tail=b"",
                capacity=65500,
            ),
        )
    )


def _write(path: Path, disk: Disk | None = None) -> Path:
    data, _ = fds.encode(disk or _disk(), headered=False)
    path.write_bytes(data)
    return path


def test_a_foreign_image_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "foreign.qd"
    path.write_bytes(b"HXCQDDRV" + bytes(65528))

    with pytest.raises(typer.Exit):
        decode_image(path)


def test_an_empty_cluster_set_has_no_margin() -> None:
    empty = IntervalReport(pulses=0, clusters=(), separations=(), outliers=0, rpm=None)

    assert empty.worst_margin == 0.0


def test_a_track_of_one_revolution_has_no_speed_spread() -> None:
    report = TrackReport(
        index=0,
        revolutions=(IntervalReport(pulses=0, clusters=(), separations=(), outliers=0, rpm=96.0),),
    )

    assert report.rpm_spread == 0.0


def test_several_revolutions_give_a_speed_spread() -> None:
    capture = synthesise(_disk(), revolutions=2, jitter_ns=200, seed=4)

    assert analyse_capture(capture).tracks[0].rpm_spread >= 0.0


def test_a_single_interval_still_fits() -> None:
    assert analyse_intervals((10_400,)).base_ns > 0


def test_an_empty_confidence_report_scores_nothing() -> None:
    assert ConfidenceReport(blocks=()).mean == 0.0


def test_a_statistics_report_with_no_block_is_stable() -> None:
    assert ReadStatistics(passes=2, blocks=()).stability == 1.0


def test_a_group_with_no_member_has_no_agreement() -> None:
    group = GroupMaster(
        key=GameKey(game_code="ABC", version=0, disk_number=0, sides=1),
        members=(),
        digest="d",
        variants=0,
        consensus=None,
    )

    assert group.agreement == 0.0


def test_a_drive_that_compared_nothing_has_no_error_rate() -> None:
    assert DriveProfile(passes=0, blocks_compared=0, blocks_wrong=0).error_rate == 0.0


def test_an_empty_code_report_has_no_share() -> None:
    assert CodeReport(examined=0, illegal=0).share == 0.0


def test_a_flux_report_adds_a_reason_to_the_grade() -> None:
    capture = synthesise(_disk())
    flux = analyse_capture(capture)

    report = grade_disk(confidence=score_disk(_disk()), flux=flux)

    assert any(reason.metric == "flux margin" for reason in report.reasons)


def test_a_homepage_is_written_into_the_dat() -> None:
    text = build_dat([("A.fds", b"x")], name="F", version="1", homepage="https://example.test")

    assert "https://example.test" in text


def test_the_flux_command_prints_speed_and_outliers(tmp_path: Path) -> None:
    path = tmp_path / "capture.counts"
    capture = synthesise(_disk())
    stretched = FluxCapture(
        source=capture.source,
        tracks=(
            FluxTrack(
                index=0,
                revolutions=(Revolution(intervals=(*capture.track(0).intervals(), 900_000)),),
            ),
        ),
    )
    path.write_bytes(write_counts(stretched))

    result = runner.invoke(app, ["flux", str(path)])

    assert "speed" in result.stdout
    assert "outliers" in result.stdout


def test_decoding_a_capture_with_no_pulse_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "capture.raw"
    path.write_bytes(bytes(1))

    result = runner.invoke(app, ["flux-decode", str(path), "-o", str(tmp_path / "o.fds")])

    assert result.exit_code == 1


def test_decoding_prints_a_finding(tmp_path: Path) -> None:
    path = tmp_path / "capture.raw"
    path.write_bytes(bytes([60]) * 4000)

    result = runner.invoke(app, ["flux-decode", str(path), "-o", str(tmp_path / "o.fds")])

    assert "[FDS014]" in result.stdout


def test_splicing_a_donor_of_another_shape_is_refused(tmp_path: Path) -> None:
    image = _write(tmp_path / "a.fds")
    other = Disk(
        sides=(
            Side(
                blocks=(
                    Block(kind=BlockKind.DISK_INFO, payload=_payload()),
                    Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([2, 1])),
                ),
                tail=b"",
                capacity=65500,
            ),
        )
    )
    donor = _write(tmp_path / "b.fds", other)

    result = runner.invoke(
        app, ["splice", str(image), "--donor", str(donor), "-o", str(tmp_path / "o.fds")]
    )

    assert result.exit_code == 1
    assert "different shape" in result.stdout


def test_a_contested_corpus_prints_the_dissenters(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    _write(root / "a.fds")
    _write(root / "b.fds", _disk(licensee=0x99))

    result = runner.invoke(app, ["masters", str(root)])

    assert "dissenting" in result.stdout


def test_building_a_reference_with_an_unknown_profile_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    _write(root / "a.fds")

    result = runner.invoke(
        app,
        [
            "reference-build",
            str(root),
            "-o",
            str(tmp_path / "set.json"),
            "--set-version",
            "1",
            "--profile",
            "nope",
        ],
    )

    assert result.exit_code == 1
    assert "unknown profile" in result.stdout


def test_a_mismatching_image_prints_the_expected_digest(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    _write(root / "a.fds")
    reference = tmp_path / "set.json"
    runner.invoke(app, ["reference-build", str(root), "-o", str(reference), "--set-version", "1"])
    other = _write(tmp_path / "other.fds", _disk(licensee=0x77))

    result = runner.invoke(app, ["reference-verify", str(other), "--set", str(reference)])

    assert result.exit_code == 1
    assert "expected" in result.stdout


def test_a_dat_from_a_missing_directory_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "dat-build",
            str(tmp_path / "nowhere"),
            "-o",
            str(tmp_path / "o.dat"),
            "--name",
            "F",
            "--set-version",
            "1",
        ],
    )

    assert result.exit_code == 1
    assert "directory not found" in result.stdout


def test_grading_against_a_dump_of_another_shape_is_refused(tmp_path: Path) -> None:
    image = _write(tmp_path / "a.fds")
    other = Disk(
        sides=(
            Side(
                blocks=(
                    Block(kind=BlockKind.DISK_INFO, payload=_payload()),
                    Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([2, 1])),
                ),
                tail=b"",
                capacity=65500,
            ),
        )
    )
    second = _write(tmp_path / "b.fds", other)

    result = runner.invoke(app, ["grade", str(image), "--read", str(second)])

    assert result.exit_code == 1
    assert "different shapes" in result.stdout


def test_calibration_can_print_json(tmp_path: Path) -> None:
    reference = _write(tmp_path / "ref.fds")
    read = _write(tmp_path / "r.fds")

    result = runner.invoke(app, ["calibrate", str(reference), "--read", str(read), "--json"])

    assert result.exit_code == 0
    assert '"verdict": "good"' in result.stdout


def test_an_unsound_image_lists_its_suspicions(tmp_path: Path) -> None:
    header = bytearray(16)
    header[0x00] = BlockKind.FILE_HEADER
    header[0x03:0x0B] = b"PRG     "
    header[0x0D:0x0F] = (200).to_bytes(2, "little")
    disk = Disk(
        sides=(
            Side(
                blocks=(
                    Block(kind=BlockKind.DISK_INFO, payload=_payload()),
                    Block(kind=BlockKind.FILE_AMOUNT, payload=bytes([2, 1])),
                    Block(kind=BlockKind.FILE_HEADER, payload=bytes(header)),
                    Block(kind=BlockKind.FILE_DATA, payload=bytes([4]) + bytes((0x02,)) * 200),
                ),
                tail=b"",
                capacity=65500,
            ),
        )
    )
    image = _write(tmp_path / "a.fds", disk)

    result = runner.invoke(app, ["integrity", str(image)])

    assert result.exit_code == 1
    assert "implausible code" in result.stdout


def test_a_reference_set_from_an_empty_corpus_holds_nothing() -> None:
    reference = reference_from(build_masters([]), version="1")

    assert ReferenceSet.from_json(reference.to_json()).entries == ()


def test_a_stream_of_zero_intervals_still_reports() -> None:
    report = analyse_intervals((0, 0, 0))

    assert report.base_ns == 0.0
    assert report.bit_rate_hz == 0.0


def test_a_capture_holding_no_pulse_is_refused_by_decode(tmp_path: Path) -> None:
    path = tmp_path / "empty.counts"
    path.write_bytes(b"")

    result = runner.invoke(app, ["flux-decode", str(path), "-o", str(tmp_path / "o.fds")])

    assert result.exit_code == 1
    assert "empty" in result.stdout


def test_measuring_a_capture_holding_no_pulse_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "empty.counts"
    path.write_bytes(b"")

    result = runner.invoke(app, ["flux", str(path)])

    assert result.exit_code == 1
    assert "empty" in result.stdout


def test_an_unknown_image_prints_no_game(tmp_path: Path) -> None:
    root = tmp_path / "corpus"
    root.mkdir()
    _write(root / "a.fds")
    reference = tmp_path / "set.json"
    runner.invoke(app, ["reference-build", str(root), "-o", str(reference), "--set-version", "1"])

    payload = bytearray(_payload())
    payload[0x10:0x13] = b"ZZZ"
    other = _write(
        tmp_path / "z.fds",
        Disk(
            sides=(
                Side(
                    blocks=(Block(kind=BlockKind.DISK_INFO, payload=bytes(payload)),),
                    tail=b"",
                    capacity=65500,
                ),
            )
        ),
    )

    result = runner.invoke(app, ["reference-verify", str(other), "--set", str(reference)])

    assert result.exit_code == 1
    assert "unknown" in result.stdout
    assert "game " not in result.stdout


def test_a_capture_with_no_elapsed_time_reports_no_speed(tmp_path: Path) -> None:
    path = tmp_path / "flat.raw"
    path.write_bytes(bytes(64))

    result = runner.invoke(app, ["flux", str(path)])

    assert "speed" not in result.stdout
