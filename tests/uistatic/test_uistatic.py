from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from page_kit import ASSETS, SCRIPT_NAME, built_page

from fdstoolkit.ui.app import (
    ROUTE_FOR_COMMAND,
    UNBUILT_STAMP,
    asset_root,
    asset_stamp,
    create_app,
)

OK = 200
SERVICE_UNAVAILABLE = 503
SOURCE = Path("web")
MARKUP = (SOURCE / "index.html").read_text(encoding="utf-8")
SCRIPT = "\n".join(
    path.read_text(encoding="utf-8")
    for path in sorted((SOURCE / "src").rglob("*.ts*"))
    if not path.name.endswith(".d.ts")
)
STYLES = "\n".join(
    path.read_text(encoding="utf-8") for path in sorted((SOURCE / "src/styles").glob("*.css"))
)
TARGET_SIZE_PX = 44


@pytest.fixture(name="built")
def built_fixture(tmp_path: Path) -> Path:
    return built_page(tmp_path)


@pytest.fixture(name="client")
def client_fixture(built: Path) -> TestClient:
    return TestClient(create_app(page_dir=built), base_url="http://127.0.0.1")


@pytest.mark.parametrize("name", ASSETS)
def test_the_built_files_are_served(client: TestClient, name: str) -> None:
    # Arrange
    route = f"/static/{name}"

    # Act
    answer = client.get(route)

    # Assert
    assert answer.status_code == OK


@pytest.mark.parametrize("name", ASSETS)
def test_an_upgraded_asset_is_not_served_from_a_stale_cache(client: TestClient, name: str) -> None:
    # Arrange
    expected = "no-cache"

    # Act
    result = client.get(f"/static/{name}").headers["cache-control"]

    # Assert
    assert result == expected


def test_an_answer_that_is_not_an_asset_is_left_cacheable(client: TestClient) -> None:
    # Arrange
    route = "/api/forms"

    # Act
    answer = client.get(route)

    # Assert
    assert "cache-control" not in answer.headers


def test_the_page_asks_for_assets_under_a_stamp_the_content_decides(
    client: TestClient, built: Path
) -> None:
    # Arrange
    route = "/"

    # Act
    markup = client.get(route).text

    # Assert
    assert f"{asset_root(built)}/assets/{SCRIPT_NAME}" in markup
    assert "/static/" not in markup


def test_the_page_script_carries_the_nonce_its_policy_allows(client: TestClient) -> None:
    # Arrange
    route = "/"

    # Act
    answer = client.get(route)

    # Assert
    nonce = re.search(r'<script type="module" nonce="([^"]+)" crossorigin', answer.text)
    assert nonce is not None
    assert f"'nonce-{nonce.group(1)}'" in answer.headers["content-security-policy"]


def test_the_page_itself_is_never_cached_so_a_new_stamp_always_arrives(
    client: TestClient,
) -> None:
    # Arrange
    expected = "no-store"

    # Act
    result = client.get("/").headers["cache-control"]

    # Assert
    assert result == expected


@pytest.mark.parametrize("name", ASSETS)
def test_a_stamped_asset_is_served_and_may_be_kept_forever(
    client: TestClient, built: Path, name: str
) -> None:
    # Arrange
    route = f"{asset_root(built)}/{name}"

    # Act
    answer = client.get(route)

    # Assert
    assert answer.status_code == OK
    assert "immutable" in answer.headers["cache-control"]


def test_a_page_that_was_never_built_says_how_to_build_it(tmp_path: Path) -> None:
    # Arrange
    client = TestClient(create_app(page_dir=tmp_path / "missing"), base_url="http://127.0.0.1")

    # Act
    answer = client.get("/")

    # Assert
    assert answer.status_code == SERVICE_UNAVAILABLE
    assert "pnpm build" in answer.text
    assert answer.headers["cache-control"] == "no-store"


def test_a_missing_page_folder_has_a_stamp_of_its_own(tmp_path: Path) -> None:
    # Arrange
    folder = tmp_path / "missing"

    # Act
    stamp = asset_stamp(folder)

    # Assert
    assert stamp == UNBUILT_STAMP


def test_the_stamp_follows_the_bytes_of_every_asset(tmp_path: Path) -> None:
    # Arrange
    before = _stamp_over(tmp_path, {"index.html": b"one"})

    # Act
    after = _stamp_over(tmp_path, {"index.html": b"two"})

    # Assert
    assert before != after


def test_the_stamp_holds_still_while_the_assets_do(tmp_path: Path) -> None:
    # Arrange
    once = _stamp_over(tmp_path, {"index.html": b"one"})

    # Act
    again = _stamp_over(tmp_path, {"index.html": b"one"})

    # Assert
    assert once == again


def test_a_folder_beside_the_assets_does_not_move_the_stamp(tmp_path: Path) -> None:
    # Arrange
    plain = _stamp_over(tmp_path, {"index.html": b"one"})

    # Act
    with_folder = _stamp_over(tmp_path, {"index.html": b"one"}, folders=("cache",))

    # Assert
    assert plain == with_folder


def _stamp_over(root: Path, files: dict[str, bytes], folders: tuple[str, ...] = ()) -> str:
    folder = root / str(len(list(root.iterdir())))
    folder.mkdir()
    for name, body in files.items():
        (folder / name).write_bytes(body)
    for name in folders:
        (folder / name).mkdir()
    return asset_stamp(folder)


def test_the_markup_is_a_complete_document() -> None:
    # Arrange
    markup = MARKUP

    # Act
    trimmed = markup.rstrip()

    # Assert
    assert markup.startswith("<!doctype html>")
    assert trimmed.endswith("</html>")


def test_the_page_declares_a_language_and_a_viewport() -> None:
    # Arrange
    markup = MARKUP

    # Act
    declared = ('<html lang="en">' in markup, 'name="viewport"' in markup)

    # Assert
    assert declared == (True, True)


def test_the_page_has_exactly_one_top_level_heading() -> None:
    # Arrange
    expected = 1

    # Act
    result = SCRIPT.count("<h1")

    # Assert
    assert result == expected


def test_no_heading_level_is_skipped() -> None:
    # Arrange
    pattern = r"<h([1-6])"

    # Act
    levels = [int(found) for found in re.findall(pattern, SCRIPT)]

    # Assert
    assert levels
    assert max(levels) - min(levels) < len(set(levels))


def test_the_page_renders_its_commands_from_the_catalogue() -> None:
    # Arrange
    needle = "catalogue.data"

    # Act
    found = needle in SCRIPT

    # Assert
    assert found
    assert 'id="commands"' in SCRIPT


def test_the_page_hardcodes_no_command() -> None:
    # Arrange
    expected: set[str] = set()

    # Act
    hardcoded = set(re.findall(r"'/api/([\w-]+)'", SCRIPT)) - {"catalogue", "hardware"}

    # Assert
    assert hardcoded == expected


def test_the_page_offers_a_control_for_every_field_kind() -> None:
    # Arrange
    kinds = ("file", "files", "flag", "number", "choice")

    # Act
    missing = [kind for kind in kinds if f"'{kind}'" not in SCRIPT]

    # Assert
    assert missing == []


def test_the_claim_about_where_data_goes_is_written_not_fetched() -> None:
    # Arrange
    claim = "t('footer.cli')"

    # Act
    written = claim in SCRIPT

    # Assert
    assert written
    assert "/api/about" not in SCRIPT


def test_every_input_carries_a_name() -> None:
    # Arrange
    inputs = len(re.findall(r"<input\b", SCRIPT))

    # Act
    named = len(re.findall(r"aria-labelledby=", SCRIPT)) + SCRIPT.count(
        '<label className="search">'
    )

    # Assert
    assert named >= inputs


def test_every_control_meets_the_target_size() -> None:
    # Arrange
    styles = STYLES

    # Act
    declared = f"min-height: {TARGET_SIZE_PX}px" in styles

    # Assert
    assert declared


def test_a_visible_focus_indicator_is_defined() -> None:
    # Arrange
    styles = STYLES

    # Act
    declared = ("focus-visible" in styles, "outline" in styles)

    # Assert
    assert declared == (True, True)


def test_reduced_motion_is_honoured() -> None:
    # Arrange
    styles = STYLES

    # Act
    declared = "prefers-reduced-motion" in styles

    # Assert
    assert declared


def test_a_dark_scheme_is_defined() -> None:
    # Arrange
    styles = STYLES

    # Act
    declared = "prefers-color-scheme: dark" in styles

    # Assert
    assert declared


def test_the_page_covers_every_command_the_catalogue_names(client: TestClient) -> None:
    # Arrange
    iterable = client.get("/api/catalogue").json()["commands"]

    # Act
    listed = set(iterable)

    # Assert
    assert listed == set(ROUTE_FOR_COMMAND)


def test_every_endpoint_the_script_calls_is_registered() -> None:
    # Arrange
    called = set(re.findall(r"path: '(/api/[\w/-]+)'", SCRIPT))

    # Act
    registered = set(ROUTE_FOR_COMMAND.values()) | {
        "/api/catalogue",
        "/api/hardware",
        "/api/jobs/current",
    }

    # Assert
    assert called
    assert called - registered == set()


def test_the_page_never_reaches_outside_this_machine() -> None:
    # Arrange
    script = SCRIPT

    # Act
    remote = ("http://" in script, "https://" in script, "//cdn" in MARKUP)

    # Assert
    assert remote == (False, False, False)


def test_the_markup_loads_no_remote_resource() -> None:
    # Arrange
    pattern = r'(?:src|href)="([^"]+)"'

    # Act
    sources = re.findall(pattern, MARKUP)

    # Assert
    assert sources
    assert all(source.startswith("/src/") for source in sources)
