from __future__ import annotations

from pathlib import Path

import pytest
import typer

from fdstoolkit.cli.common import Container, container_of, fail, guard_output, read_image


def test_a_message_becomes_a_failing_exit() -> None:
    error = fail("broken")

    assert isinstance(error, typer.Exit)
    assert error.exit_code == 1


def test_an_fds_suffix_names_the_fds_container(tmp_path: Path) -> None:
    assert container_of(tmp_path / "a.fds") is Container.FDS
    assert container_of(tmp_path / "a.FDS") is Container.FDS


def test_a_qd_suffix_names_the_qd_container(tmp_path: Path) -> None:
    assert container_of(tmp_path / "a.qd") is Container.QD


def test_another_suffix_is_refused(tmp_path: Path) -> None:
    with pytest.raises(typer.Exit):
        container_of(tmp_path / "a.zip")


def test_a_missing_file_is_refused(tmp_path: Path) -> None:
    with pytest.raises(typer.Exit):
        read_image(tmp_path / "missing.fds")


def test_a_present_file_comes_back_with_its_container(tmp_path: Path) -> None:
    path = tmp_path / "a.fds"
    path.write_bytes(b"data")

    data, container = read_image(path)

    assert data == b"data"
    assert container is Container.FDS


def test_an_existing_output_is_refused_without_force(tmp_path: Path) -> None:
    path = tmp_path / "out.fds"
    path.write_bytes(b"")

    with pytest.raises(typer.Exit):
        guard_output(path, force=False)


def test_an_existing_output_is_allowed_with_force(tmp_path: Path) -> None:
    path = tmp_path / "out.fds"
    path.write_bytes(b"")

    guard_output(path, force=True)


def test_a_new_output_needs_no_force(tmp_path: Path) -> None:
    guard_output(tmp_path / "new.fds", force=False)
