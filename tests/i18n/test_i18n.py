from __future__ import annotations

import re
from pathlib import Path

import pytest

from fdstoolkit.ui.forms import forms

SOURCE = Path("web")
MARKUP = (SOURCE / "index.html").read_text(encoding="utf-8")
SCRIPT = "\n".join(
    path.read_text(encoding="utf-8")
    for path in sorted((SOURCE / "src").rglob("*.ts*"))
    if not path.name.endswith(".d.ts")
)
DICTIONARIES = (SOURCE / "src/i18n.ts").read_text(encoding="utf-8")
THE_SAME_IN_BOTH_LANGUAGES = {"title"}
LANGUAGES = ("en", "ja")
OPENINGS = {"en": "const ENGLISH: Dictionary = {", "ja": "const JAPANESE: Dictionary = {"}
STORAGE_GUARDS = 2


def _block(language: str) -> str:
    start = DICTIONARIES.index(OPENINGS[language])
    depth = 0
    for index in range(start, len(DICTIONARIES)):
        if DICTIONARIES[index] == "{":
            depth += 1
        elif DICTIONARIES[index] == "}":
            depth -= 1
            if depth == 0:
                return DICTIONARIES[start:index]
    message = f"the {language} dictionary is not closed"
    raise AssertionError(message)


def _keys(language: str) -> set[str]:
    return set(re.findall(r"^    '([\w.]+)':", _block(language), re.MULTILINE))


def _values(language: str) -> dict[str, str]:
    pairs = re.findall(
        r"^    '([\w.]+)':\s*'((?:[^'\\]|\\.)*)'",
        _block(language),
        re.MULTILINE,
    )
    return dict(pairs)


def _used_keys() -> set[str]:
    return set(re.findall(r"\b(?:t|speak)\('([\w.]+)'", SCRIPT))


def test_both_languages_carry_the_same_keys() -> None:
    # Arrange
    expected = _keys("ja")

    # Act
    result = _keys("en")

    # Assert
    assert result == expected


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_key_the_page_uses_exists(language: str) -> None:
    # Arrange
    expected: set[str] = set()

    # Act
    result = _used_keys() - _keys(language)

    # Assert
    assert result == expected


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_dictionary_is_empty(language: str) -> None:
    # Arrange
    obj = _keys(language)

    # Act
    result = len(obj)

    # Assert
    assert result > 1


def test_every_japanese_string_is_japanese() -> None:
    # Arrange
    expected: set[str] = set()

    # Act
    untranslated = {
        key
        for key, value in _values("ja").items()
        if value.isascii() and key not in THE_SAME_IN_BOTH_LANGUAGES
    }

    # Assert
    assert untranslated == expected


def test_the_page_offers_both_languages() -> None:
    # Arrange
    script = SCRIPT

    # Act
    offered = re.findall(r"\['(\w+)', '[^']+'\]", script)

    # Assert
    assert "en" in offered
    assert "ja" in offered


def test_the_language_choice_survives_storage_being_unavailable() -> None:
    # Arrange
    path = SOURCE / "src/i18n.ts"

    # Act
    dictionaries = path.read_text(encoding="utf-8")

    # Assert
    assert dictionaries.count("try {") >= STORAGE_GUARDS
    assert "localStorage" in dictionaries


def test_the_page_script_pulls_the_dictionaries_in_itself() -> None:
    # Arrange
    path = SOURCE / "src/Page.tsx"

    # Act
    script = path.read_text(encoding="utf-8")

    # Assert
    assert "from './i18n'" in script
    assert '<script type="module" src="/src/main.tsx">' in MARKUP


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_command_family_carries_a_label(language: str) -> None:
    # Arrange
    expected: set[str] = set()

    # Act
    wanted = {f"family.{form.family}" for form in forms()}

    # Assert
    assert wanted - _keys(language) == expected


def test_no_label_names_a_family_that_does_not_exist() -> None:
    # Arrange
    expected: set[str] = set()

    # Act
    declared = {key for key in _keys("en") if key.startswith("family.")}

    # Assert
    assert declared - {f"family.{form.family}" for form in forms()} == expected


def test_no_key_is_declared_twice_in_one_language() -> None:
    # Arrange
    pattern = r"^    '([\w.]+)':"

    # Act
    declared = {
        language: re.findall(pattern, _block(language), re.MULTILINE) for language in LANGUAGES
    }

    # Assert
    assert all(len(keys) == len(set(keys)) for keys in declared.values())
