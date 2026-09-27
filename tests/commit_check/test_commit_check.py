from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash") or "/bin/bash"
GIT = shutil.which("git") or "/usr/bin/git"
SCRIPT = ROOT / "scripts" / "check-commits.sh"


def check_message(tmp_path: Path, message: str) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "COMMIT_EDITMSG"
    path.write_text(message, encoding="utf-8")
    return subprocess.run(
        [BASH, str(SCRIPT), "--message", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    "subject",
    [
        "feat(raw): read captures packed in any bit order",
        "fix: refuse a side past 255 files",
        "chore(release): 1.6.0 [skip ci]",
        "feat!: drop the old capture format",
    ],
)
def test_a_conventional_subject_passes(tmp_path: Path, subject: str) -> None:
    result = check_message(tmp_path, f"{subject}\n\nbody\n")

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("subject", "reason"),
    [
        ("Fixed the parser", "type"),
        ("fix(parse): Refuse a side", "lowercase"),
        ("fix(parse): refuse a side.", "full stop"),
        ("fix(parse): refuse a side whose declared file count is wrong", "50"),
        ("draft: try something", "type"),
    ],
)
def test_a_subject_that_breaks_the_convention_is_refused(
    tmp_path: Path, subject: str, reason: str
) -> None:
    result = check_message(tmp_path, f"{subject}\n")

    assert result.returncode == 1
    assert reason in result.stderr


def test_git_comment_lines_are_ignored(tmp_path: Path) -> None:
    result = check_message(tmp_path, "# Please enter the message\nfix: keep the finish reason\n")

    assert result.returncode == 0, result.stderr


def run_git(repository: Path, *arguments: str) -> None:
    subprocess.run([GIT, "-C", str(repository), *arguments], check=True, capture_output=True)


def test_a_range_is_refused_when_any_commit_in_it_breaks_the_convention(tmp_path: Path) -> None:
    run_git(tmp_path, "init", "-q")
    run_git(tmp_path, "config", "user.email", "check@example.invalid")
    run_git(tmp_path, "config", "user.name", "check")
    run_git(tmp_path, "commit", "-q", "--allow-empty", "-m", "chore: start")
    run_git(tmp_path, "commit", "-q", "--allow-empty", "-m", "feat: add a thing")
    run_git(tmp_path, "commit", "-q", "--allow-empty", "-m", "Added another thing")

    result = subprocess.run(
        [BASH, str(SCRIPT), "--range", "HEAD~2..HEAD"],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
    )

    assert result.returncode == 1
    assert "Added another thing" in result.stderr
    assert "feat: add a thing" not in result.stderr


def test_an_unknown_argument_is_refused(tmp_path: Path) -> None:
    result = subprocess.run(
        [BASH, str(SCRIPT), "--what"], capture_output=True, text=True, check=False, cwd=tmp_path
    )

    assert result.returncode == 2
    assert "usage" in result.stderr
