from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.ui.app import (
    ASSET_ROOT,
    ROUTE_FOR_COMMAND,
    STATIC_DIR,
    asset_stamp,
    create_app,
)

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


@pytest.mark.parametrize("name", ["app.css", "app.js", "i18n.js"])
def test_an_upgraded_asset_is_not_served_from_a_stale_cache(client: TestClient, name: str) -> None:
    assert client.get(f"/static/{name}").headers["cache-control"] == "no-cache"


def test_an_answer_that_is_not_an_asset_is_left_cacheable(client: TestClient) -> None:
    assert "cache-control" not in client.get("/api/forms").headers


def test_the_page_asks_for_assets_under_a_stamp_the_content_decides(client: TestClient) -> None:
    markup = client.get("/").text

    assert f"{ASSET_ROOT}/app.js" in markup
    assert "/static/" not in markup


def test_the_page_itself_is_never_cached_so_a_new_stamp_always_arrives(
    client: TestClient,
) -> None:
    assert client.get("/").headers["cache-control"] == "no-store"


@pytest.mark.parametrize("name", ["app.css", "app.js", "i18n.js"])
def test_a_stamped_asset_is_served_and_may_be_kept_forever(client: TestClient, name: str) -> None:
    answer = client.get(f"{ASSET_ROOT}/{name}")

    assert answer.status_code == OK
    assert "immutable" in answer.headers["cache-control"]


def test_the_stamp_follows_the_bytes_of_every_asset(tmp_path: Path) -> None:
    before = _stamp_over(tmp_path, {"app.js": b"one"})
    after = _stamp_over(tmp_path, {"app.js": b"two"})

    assert before != after


def test_the_stamp_holds_still_while_the_assets_do(tmp_path: Path) -> None:
    once = _stamp_over(tmp_path, {"app.js": b"one"})
    again = _stamp_over(tmp_path, {"app.js": b"one"})

    assert once == again


def test_a_folder_beside_the_assets_does_not_move_the_stamp(tmp_path: Path) -> None:
    plain = _stamp_over(tmp_path, {"app.js": b"one"})
    with_folder = _stamp_over(tmp_path, {"app.js": b"one"}, folders=("cache",))

    assert plain == with_folder


def _stamp_over(root: Path, files: dict[str, bytes], folders: tuple[str, ...] = ()) -> str:
    folder = root / str(len(list(root.iterdir())))
    folder.mkdir()
    for name, body in files.items():
        (folder / name).write_bytes(body)
    for name in folders:
        (folder / name).mkdir()
    with patch("fdstoolkit.ui.app.STATIC_DIR", folder):
        return asset_stamp()


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


def test_no_translated_element_wraps_a_control() -> None:
    translated = re.findall(r'<(\w+)[^>]*\bdata-i18n="[^"]*"[^>]*>(.*?)</\1>', MARKUP, re.DOTALL)
    swallowed = [
        tag for tag, inner in translated if re.search(r"<(input|select|textarea|button)", inner)
    ]

    assert swallowed == []


def test_the_page_renders_its_commands_from_the_catalogue() -> None:
    assert 'id="commands"' in MARKUP
    assert "catalogue.forms" in SCRIPT


def test_the_page_hardcodes_no_command() -> None:
    hardcoded = set(re.findall(r"'/api/([\w-]+)'", SCRIPT)) - {"catalogue", "hardware"}

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
    registered = set(ROUTE_FOR_COMMAND.values()) | {
        "/api/catalogue",
        "/api/doctor",
        "/api/hardware",
    }

    assert called - registered == set()


def test_the_page_never_reaches_outside_this_machine() -> None:
    assert "http://" not in SCRIPT
    assert "https://" not in SCRIPT
    assert "//cdn" not in MARKUP


def test_the_markup_loads_no_remote_resource() -> None:
    sources = re.findall(r'(?:src|href)="([^"]+)"', MARKUP)

    assert all(source.startswith("/static/") for source in sources)
