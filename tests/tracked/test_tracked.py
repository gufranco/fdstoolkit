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
        path.relative_to(ROOT).as_posix()
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


def test_the_page_tests_run_in_continuous_integration() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "pnpm test:coverage" in workflow
    assert "pnpm e2e" in workflow


def test_every_page_script_is_covered_by_a_test_file() -> None:
    scripts = {path.stem for path in (ROOT / "src/fdstoolkit/ui/static").glob("*.js")}
    exercised = "".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "tests/web").glob("*.test.js")
    )

    assert {name for name in scripts if f"static/{name}.js" not in exercised} == set()
