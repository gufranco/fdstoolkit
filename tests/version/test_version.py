from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import fdstoolkit
from fdstoolkit.version import VERSION

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") or "/bin/bash"
SEMVER = re.compile(r"^\d+\.\d+\.\d+([-+].*)?$")


def test_the_version_is_a_semantic_version() -> None:
    # Arrange
    pattern = SEMVER

    # Act
    matched = pattern.match(VERSION)

    # Assert
    assert matched is not None


def test_the_package_exposes_the_same_version() -> None:
    # Arrange
    package = fdstoolkit

    # Act
    exposed = package.__version__

    # Assert
    assert exposed == VERSION


def test_the_version_script_rewrites_the_one_place_it_lives(tmp_path: Path) -> None:
    # Arrange
    source = tmp_path / "src" / "fdstoolkit"
    source.mkdir(parents=True)
    (source / "version.py").write_text('VERSION = "0.1.0"\n', encoding="utf-8")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "set-version.sh").write_bytes((ROOT / "scripts" / "set-version.sh").read_bytes())

    # Act
    result = subprocess.run(
        [BASH, str(scripts / "set-version.sh"), "2.3.4"],
        capture_output=True,
        text=True,
        check=False,
    )

    # Assert
    assert result.returncode == 0
    assert (source / "version.py").read_text(encoding="utf-8") == 'VERSION = "2.3.4"\n'


def test_the_version_script_refuses_something_that_is_not_a_version(tmp_path: Path) -> None:
    # Arrange
    capture_output = True
    text = True
    check = False

    # Act
    result = subprocess.run(
        [BASH, str(ROOT / "scripts" / "set-version.sh"), "latest"],
        capture_output=capture_output,
        text=text,
        check=check,
        cwd=tmp_path,
    )

    # Assert
    assert result.returncode != 0
    assert "not a version" in result.stderr
