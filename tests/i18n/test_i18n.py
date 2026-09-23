from __future__ import annotations

import re

import pytest

from fdstoolkit.ui.app import STATIC_DIR
from fdstoolkit.ui.forms import forms

MARKUP = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
SCRIPT = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
DICTIONARIES = (STATIC_DIR / "i18n.js").read_text(encoding="utf-8")
THE_SAME_IN_BOTH_LANGUAGES = {"title"}
LANGUAGES = ("en", "ja")
STORAGE_GUARDS = 2


def _block(language: str) -> str:
    start = DICTIONARIES.index(f"  {language}: {{")
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
    markup = set(re.findall(r'data-i18n(?:-placeholder|-aria-label)?="([^"]+)"', MARKUP))
    script = set(re.findall(r"\bt\('([\w.]+)'", SCRIPT))
    return markup | script


def test_both_languages_carry_the_same_keys() -> None:
    assert _keys("en") == _keys("ja")


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_key_the_page_uses_exists(language: str) -> None:
    assert _used_keys() - _keys(language) == set()


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_dictionary_is_empty(language: str) -> None:
    assert len(_keys(language)) > 1


def test_every_japanese_string_is_japanese() -> None:
    untranslated = {
        key
        for key, value in _values("ja").items()
        if value.isascii() and key not in THE_SAME_IN_BOTH_LANGUAGES
    }

    assert untranslated == set()


def test_the_page_offers_both_languages() -> None:
    assert 'data-language="en"' in MARKUP
    assert 'data-language="ja"' in MARKUP


def test_the_language_choice_survives_storage_being_unavailable() -> None:
    assert DICTIONARIES.count("try {") >= STORAGE_GUARDS
    assert "localStorage" in DICTIONARIES


def test_the_dictionaries_load_before_the_page_script() -> None:
    assert MARKUP.index("/static/i18n.js") < MARKUP.index("/static/app.js")


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_command_family_carries_a_label(language: str) -> None:
    wanted = {f"family.{form.family}" for form in forms()}

    assert wanted - _keys(language) == set()


def test_no_label_names_a_family_that_does_not_exist() -> None:
    declared = {key for key in _keys("en") if key.startswith("family.")}

    assert declared - {f"family.{form.family}" for form in forms()} == set()


def test_no_key_is_declared_twice_in_one_language() -> None:
    for language in LANGUAGES:
        declared = re.findall(r"^    '([\w.]+)':", _block(language), re.MULTILINE)

        assert len(declared) == len(set(declared))
