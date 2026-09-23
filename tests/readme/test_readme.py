from __future__ import annotations

import re
from pathlib import Path

import pytest

from fdstoolkit.cli.main import app

READMES = ("README.md", "README.ja.md")
HOMEBREW_DESC_LIMIT = 80


def commands() -> set[str]:
    return {
        command.name or command.callback.__name__.replace("_", "-")
        for command in app.registered_commands
        if command.callback is not None
    }


def documented(text: str) -> set[str]:
    found: set[str] = set()
    for line in text.splitlines():
        if line.startswith("#### "):
            found.update(re.findall(r"`([a-z][\w-]*)", line))
    return found


@pytest.mark.parametrize("name", READMES)
def test_every_command_is_documented(name: str) -> None:
    text = Path(name).read_text(encoding="utf-8")

    assert commands() - documented(text) == set()


@pytest.mark.parametrize("name", READMES)
def test_no_entry_names_a_command_that_does_not_exist(name: str) -> None:
    text = Path(name).read_text(encoding="utf-8")

    assert documented(text) - commands() == set()


def test_both_languages_document_the_same_commands() -> None:
    english = documented(Path("README.md").read_text(encoding="utf-8"))
    japanese = documented(Path("README.ja.md").read_text(encoding="utf-8"))

    assert english == japanese


@pytest.mark.parametrize("name", READMES)
def test_every_command_block_is_a_bash_block(name: str) -> None:
    text = Path(name).read_text(encoding="utf-8")

    assert "```console" not in text


def test_the_two_readmes_point_at_each_other() -> None:
    assert "README.ja.md" in Path("README.md").read_text(encoding="utf-8")
    assert "README.md" in Path("README.ja.md").read_text(encoding="utf-8")


def referenced(name: str) -> set[str]:
    text = Path(name).read_text(encoding="utf-8")
    return set(re.findall(r'(?:src|srcset)="(assets/screenshots/[\w-]+\.png)"', text))


@pytest.mark.parametrize("name", READMES)
def test_every_screenshot_it_shows_exists(name: str) -> None:
    missing = {path for path in referenced(name) if not Path(path).is_file()}

    assert missing == set()


@pytest.mark.parametrize("name", READMES)
def test_every_command_carries_a_screenshot(name: str) -> None:
    shown = {Path(path).stem.rsplit("-", maxsplit=1)[0] for path in referenced(name)}

    assert commands() - shown - {"web"} == set()


@pytest.mark.parametrize("name", READMES)
def test_both_schemes_are_offered_for_every_shot(name: str) -> None:
    shots = referenced(name)
    light = {path for path in shots if path.endswith("-light.png")}

    assert len(light) * 2 == len(shots)


def test_no_screenshot_on_disk_goes_unused() -> None:
    on_disk = {
        f"assets/screenshots/{path.name}" for path in Path("assets/screenshots").glob("*.png")
    }

    assert on_disk - referenced("README.md") == set()


def readme_opening() -> str:
    for line in Path("README.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("A command-line toolkit"):
            return line.strip()
    message = "the README no longer opens with a description"
    raise AssertionError(message)


def test_the_package_description_is_the_readme_sentence() -> None:
    manifest = Path("pyproject.toml").read_text(encoding="utf-8")

    assert f'description = "{readme_opening()}"' in manifest


def test_the_formula_description_is_made_from_the_readme() -> None:
    formula = Path("Formula/fdstoolkit.rb").read_text(encoding="utf-8")
    desc = re.search(r'^\s*desc "([^"]+)"', formula, re.MULTILINE)

    assert desc is not None
    readme = Path("README.md").read_text(encoding="utf-8").lower()
    for word in re.findall(r"[a-z]{4,}", desc.group(1).lower()):
        assert word in readme


def test_the_formula_description_meets_the_homebrew_rules() -> None:
    formula = Path("Formula/fdstoolkit.rb").read_text(encoding="utf-8")
    desc = re.search(r'^\s*desc "([^"]+)"', formula, re.MULTILINE)

    assert desc is not None
    text = desc.group(1)
    assert not text.endswith(".")
    assert not text.lower().startswith(("a ", "an ", "the "))
    assert len(text) <= HOMEBREW_DESC_LIMIT
