from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.ui.app import ROUTE_FOR_COMMAND, STATIC_DIR, create_app

OK = 200
MARKUP = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
SCRIPT = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
STYLES = (STATIC_DIR / "app.css").read_text(encoding="utf-8")
TARGET_SIZE_PX = 44


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app())


def test_every_static_file_is_present() -> None:
    for name in ("index.html", "app.css", "app.js", "i18n.js"):
        assert (STATIC_DIR / name).is_file()


@pytest.mark.parametrize("name", ["app.css", "app.js", "i18n.js"])
def test_the_static_files_are_served(client: TestClient, name: str) -> None:
    assert client.get(f"/static/{name}").status_code == OK


def test_the_markup_is_a_complete_document() -> None:
    assert MARKUP.startswith("<!doctype html>")
    assert MARKUP.rstrip().endswith("</html>")


def test_the_page_declares_a_language_and_a_viewport() -> None:
    assert '<html lang="en">' in MARKUP
    assert 'name="viewport"' in MARKUP


def test_the_page_has_exactly_one_top_level_heading() -> None:
    assert MARKUP.count("<h1") == 1


def test_no_heading_level_is_skipped() -> None:
    levels = [int(found) for found in re.findall(r"<h([1-6])", MARKUP)]

    assert levels
    assert max(levels) - min(levels) < len(set(levels))


def test_the_page_renders_its_commands_from_the_catalogue() -> None:
    assert 'id="commands"' in MARKUP
    assert "catalogue.forms" in SCRIPT


def test_the_page_hardcodes_no_command() -> None:
    hardcoded = set(re.findall(r"'/api/([\w-]+)'", SCRIPT)) - {"catalogue"}

    assert hardcoded == set()


def test_the_page_offers_a_control_for_every_field_kind() -> None:
    for kind in ("file", "files", "flag", "number", "choice"):
        assert f"'{kind}'" in SCRIPT


def test_the_claim_about_where_data_goes_is_in_the_markup_not_fetched() -> None:
    assert 'data-i18n="drop.hint"' in MARKUP
    assert "/api/about" not in SCRIPT


def test_the_claim_that_the_page_computes_nothing_is_in_the_markup() -> None:
    assert 'data-i18n="footer.cli"' in MARKUP


def test_every_input_carries_a_label() -> None:
    inputs = re.findall(r"<input[^>]*>", MARKUP)
    labelled = re.findall(r"<label[^>]*>", MARKUP)

    assert len(labelled) >= len(inputs) - MARKUP.count('type="checkbox"')


def test_every_control_meets_the_target_size() -> None:
    assert f"min-height: {TARGET_SIZE_PX}px" in STYLES


def test_a_visible_focus_indicator_is_defined() -> None:
    assert "focus-visible" in STYLES
    assert "outline" in STYLES


def test_reduced_motion_is_honoured() -> None:
    assert "prefers-reduced-motion" in STYLES


def test_a_dark_scheme_is_defined() -> None:
    assert "prefers-color-scheme: dark" in STYLES


def test_the_page_covers_every_command_the_catalogue_names(client: TestClient) -> None:
    listed = set(client.get("/api/catalogue").json()["commands"])

    assert listed == set(ROUTE_FOR_COMMAND)


def test_every_endpoint_the_script_calls_is_registered() -> None:
    called = set(re.findall(r"call\('(/api/[\w-]+)'", SCRIPT))
    registered = set(ROUTE_FOR_COMMAND.values()) | {"/api/catalogue", "/api/doctor"}

    assert called - registered == set()


def test_the_page_never_reaches_outside_this_machine() -> None:
    assert "http://" not in SCRIPT
    assert "https://" not in SCRIPT
    assert "//cdn" not in MARKUP


def test_the_markup_loads_no_remote_resource() -> None:
    sources = re.findall(r'(?:src|href)="([^"]+)"', MARKUP)

    assert all(source.startswith("/static/") for source in sources)
