from __future__ import annotations

import re
from pathlib import Path

import pytest

from fdstoolkit.cli.common import Family
from fdstoolkit.cli.main import app

READMES = ("README.md", "README.ja.md")
REFERENCES = ("REFERENCE.md", "REFERENCE.ja.md")
PAGES = READMES + REFERENCES


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


@pytest.mark.parametrize("name", REFERENCES)
def test_every_command_is_documented(name: str) -> None:
    # Arrange
    encoding = "utf-8"

    # Act
    text = Path(name).read_text(encoding=encoding)

    # Assert
    assert commands() - documented(text) == set()


@pytest.mark.parametrize("name", REFERENCES)
def test_no_entry_names_a_command_that_does_not_exist(name: str) -> None:
    # Arrange
    encoding = "utf-8"

    # Act
    text = Path(name).read_text(encoding=encoding)

    # Assert
    assert documented(text) - commands() == set()


def test_both_languages_document_the_same_commands() -> None:
    # Arrange
    english = documented(Path("REFERENCE.md").read_text(encoding="utf-8"))

    # Act
    japanese = documented(Path("REFERENCE.ja.md").read_text(encoding="utf-8"))

    # Assert
    assert english == japanese


@pytest.mark.parametrize("name", PAGES)
def test_every_command_block_is_a_bash_block(name: str) -> None:
    # Arrange
    encoding = "utf-8"

    # Act
    text = Path(name).read_text(encoding=encoding)

    # Assert
    assert "```console" not in text


def test_the_two_readmes_point_at_each_other() -> None:
    # Arrange
    english, japanese = Path("README.md"), Path("README.ja.md")

    # Act
    texts = (english.read_text(encoding="utf-8"), japanese.read_text(encoding="utf-8"))

    # Assert
    assert "README.ja.md" in texts[0]
    assert "README.md" in texts[1]


def referenced(name: str) -> set[str]:
    text = Path(name).read_text(encoding="utf-8")
    return set(re.findall(r'(?:src|srcset)="(assets/screenshots/[\w-]+\.png)"', text))


@pytest.mark.parametrize("name", REFERENCES)
def test_every_screenshot_it_shows_exists(name: str) -> None:
    # Arrange
    expected: set[str] = set()

    # Act
    missing = {path for path in referenced(name) if not Path(path).is_file()}

    # Assert
    assert missing == expected


@pytest.mark.parametrize("name", REFERENCES)
def test_every_command_carries_a_screenshot(name: str) -> None:
    # Arrange
    expected: set[str] = set()

    # Act
    shown = {Path(path).stem.rsplit("-", maxsplit=1)[0] for path in referenced(name)}

    # Assert
    assert commands() - shown - {"web", "doctor"} == expected


@pytest.mark.parametrize("name", REFERENCES)
def test_both_schemes_are_offered_for_every_shot(name: str) -> None:
    # Arrange
    shots = referenced(name)

    # Act
    light = {path for path in shots if path.endswith("-light.png")}

    # Assert
    assert len(light) * 2 == len(shots)


def test_no_screenshot_on_disk_goes_unused() -> None:
    # Arrange
    expected: set[str] = set()

    # Act
    on_disk = {
        f"assets/screenshots/{path.name}" for path in Path("assets/screenshots").glob("*.png")
    }

    # Assert
    assert on_disk - referenced("REFERENCE.md") == expected


def readme_opening() -> str:
    for line in Path("README.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("A command-line toolkit"):
            return line.strip()
    message = "the README no longer opens with a description"
    raise AssertionError(message)


def test_the_package_description_is_the_readme_sentence() -> None:
    # Arrange
    encoding = "utf-8"

    # Act
    manifest = Path("pyproject.toml").read_text(encoding=encoding)

    # Assert
    assert f'description = "{readme_opening()}"' in manifest


def reference_headings(name: str, start: str) -> list[str]:
    lines = Path(name).read_text(encoding="utf-8").splitlines()
    begin = lines.index(start)
    end = next(index for index in range(begin + 1, len(lines)) if lines[index].startswith("## "))
    return [line[4:] for line in lines[begin:end] if line.startswith("### ")]


def japanese_labels() -> dict[str, str]:
    text = Path("src/fdstoolkit/ui/static/i18n.js").read_text(encoding="utf-8")
    japanese = text[text.index("  ja: {") :]
    return dict(re.findall(r"'family\.([a-z]+)': '([^']+)'", japanese))


def test_the_command_reference_is_grouped_by_the_declared_families() -> None:
    # Arrange
    expected = [family.value for family in Family]

    # Act
    headings = reference_headings("REFERENCE.md", "## Command reference")

    # Assert
    assert headings == expected


def test_the_japanese_command_reference_uses_the_page_labels() -> None:
    # Arrange
    headings = reference_headings("REFERENCE.ja.md", "## コマンドリファレンス")

    # Act
    labels = japanese_labels()

    # Assert
    assert headings == [labels[family.value.lower()] for family in Family]


@pytest.mark.parametrize(
    ("readme", "reference"), [("README.md", "REFERENCE.md"), ("README.ja.md", "REFERENCE.ja.md")]
)
def test_each_readme_and_its_reference_point_at_each_other(readme: str, reference: str) -> None:
    # Arrange
    guide, full = Path(readme), Path(reference)

    # Act
    texts = (guide.read_text(encoding="utf-8"), full.read_text(encoding="utf-8"))

    # Assert
    assert f"]({reference}" in texts[0]
    assert f"]({readme})" in texts[1]


@pytest.mark.parametrize("name", READMES)
def test_the_guide_links_every_command_to_its_reference_entry(name: str) -> None:
    # Arrange
    reference = "REFERENCE.ja.md" if name.endswith(".ja.md") else "REFERENCE.md"

    # Act
    linked = set(
        re.findall(
            rf"\]\({re.escape(reference)}#([a-z][\w-]*)\)", Path(name).read_text(encoding="utf-8")
        )
    )

    # Assert
    assert commands() - linked == set()
