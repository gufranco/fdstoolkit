from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.ui.app import ROUTE_FOR_COMMAND, create_app
from fdstoolkit.ui.forms import FIELD_KINDS, form_for, forms, model_for
from fdstoolkit.ui.schemas import ImageSpec

GET_ONLY = {"status"}


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app(), base_url="http://127.0.0.1")


def test_every_command_with_a_route_has_a_form() -> None:
    # Arrange
    expected = set(ROUTE_FOR_COMMAND)

    # Act
    built = {form.command for form in forms()}

    # Assert
    assert built == expected


def test_every_command_that_takes_a_body_offers_fields() -> None:
    # Arrange
    every = forms()

    # Act
    empty = {form.command for form in every if not form.fields}

    # Assert
    assert empty == GET_ONLY


def test_a_form_names_its_route_and_method() -> None:
    # Arrange
    command = "verify"

    # Act
    form = form_for(command)

    # Assert
    assert form.command == "verify"
    assert form.route == ROUTE_FOR_COMMAND["verify"]
    assert form.method == "POST"


def test_a_command_with_no_body_is_a_get() -> None:
    # Arrange
    expected = "GET"

    # Act
    result = form_for("status").method

    # Assert
    assert result == expected
    assert form_for("status").fields == []


def test_an_image_field_is_offered_as_a_file() -> None:
    # Arrange
    expected = "file"

    # Act
    kinds = {field.name: field.kind for field in form_for("verify").fields}

    # Assert
    assert kinds["data"] == expected


def test_a_list_of_images_is_offered_as_several_files() -> None:
    # Arrange
    expected = "files"

    # Act
    kinds = {field.name: field.kind for field in form_for("reads").fields}

    # Assert
    assert kinds["images"] == expected


def test_a_flag_is_offered_as_a_checkbox() -> None:
    # Arrange
    expected = "flag"

    # Act
    kinds = {field.name: field.kind for field in form_for("verify").fields}

    # Assert
    assert kinds["strict"] == expected


def test_a_number_is_offered_as_a_number() -> None:
    # Arrange
    expected = "number"

    # Act
    kinds = {field.name: field.kind for field in form_for("dump").fields}

    # Assert
    assert kinds["retries"] == expected


@pytest.mark.parametrize("command", ["blank", "dump", "surface"])
def test_a_side_count_is_offered_as_one_or_two(command: str) -> None:
    # Arrange
    expected = "choice"

    # Act
    field = next(entry for entry in form_for(command).fields if entry.name == "sides")

    # Assert
    assert field.kind == expected
    assert field.options == ["1", "2"]
    assert field.default == 1
    assert field.step == 1


def test_a_profile_field_carries_its_choices() -> None:
    # Arrange
    form = form_for("hash")

    # Act
    field = next(entry for entry in form.fields if entry.name == "profile")

    # Assert
    assert "release" in field.options


def test_every_kind_a_form_uses_is_one_the_page_knows() -> None:
    # Arrange
    expected = set(FIELD_KINDS)

    # Act
    used = {field.kind for form in forms() for field in form.fields}

    # Assert
    assert used <= expected


def test_the_catalogue_serves_every_form(client: TestClient) -> None:
    # Arrange
    expected = len(forms())

    # Act
    body = client.get("/api/catalogue").json()

    # Assert
    assert len(body["forms"]) == expected
    assert {entry["command"] for entry in body["forms"]} == set(ROUTE_FOR_COMMAND)


def test_a_required_field_is_marked() -> None:
    # Arrange
    form = form_for("verify")

    # Act
    field = next(entry for entry in form.fields if entry.name == "data")

    # Assert
    assert field.required


def test_a_field_with_a_default_is_not_required() -> None:
    # Arrange
    form = form_for("verify")

    # Act
    field = next(entry for entry in form.fields if entry.name == "strict")

    # Assert
    assert not field.required


def test_a_command_that_is_not_mapped_is_refused() -> None:
    # Arrange
    command = "nonsense"

    # Act
    with pytest.raises(KeyError) as raised:
        form_for(command)

    # Assert
    assert raised.type is KeyError


def test_a_handler_whose_only_hint_is_its_return_offers_no_fields() -> None:
    # Arrange
    expected = None

    # Act
    def handler() -> str:
        return ""

    # Assert
    assert model_for(handler) is expected


def test_a_handler_with_a_plain_parameter_skips_it_and_finds_the_model() -> None:
    # Arrange
    def handler(count: int, spec: ImageSpec) -> str:
        del count, spec
        return ""

    # Act
    model = model_for(handler)

    # Assert
    assert model is ImageSpec


@pytest.mark.parametrize("command", ["write", "surface"])
def test_the_erase_confirmation_is_asked_by_the_page_not_offered_as_a_field(command: str) -> None:
    # Arrange
    form = form_for(command)

    # Act
    confirm = next(field for field in form.fields if field.name == "confirm")

    # Assert
    assert confirm.hidden
