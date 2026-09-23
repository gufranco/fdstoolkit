from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def git(*arguments: str) -> list[str]:
    binary = shutil.which("git")
    if binary is None:
        pytest.skip("git is not on the path here")
    finished = subprocess.run(
        [binary, "-C", str(ROOT), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if finished.returncode:
        pytest.skip("git could not read this checkout")
    return [line for line in finished.stdout.splitlines() if line]


def on_disk() -> set[str]:
    return {
        str(path.relative_to(ROOT))
        for path in (ROOT / "tests").rglob("test_*.py")
        if "__pycache__" not in path.parts
    }


def tracked() -> set[str]:
    return set(git("ls-files", "tests"))


def test_every_test_file_is_tracked_by_git() -> None:
    assert on_disk() - tracked() == set()


def test_no_python_file_is_hidden_from_a_clean_checkout() -> None:
    hidden = git("-c", "core.excludesFile=/dev/null", "status", "--porcelain", "-uall")

    assert [line for line in hidden if line.startswith("??") and line.endswith(".py")] == []
