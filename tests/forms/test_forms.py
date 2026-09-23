from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fdstoolkit.ui.app import ROUTE_FOR_COMMAND, create_app
from fdstoolkit.ui.forms import FIELD_KINDS, form_for, forms, model_for
from fdstoolkit.ui.schemas import ImageSpec

GET_ONLY = {"doctor", "dat-cache"}


@pytest.fixture(name="client")
def client_fixture() -> TestClient:
    return TestClient(create_app())


def test_every_command_with_a_route_has_a_form() -> None:
    built = {form.command for form in forms()}

    assert built == set(ROUTE_FOR_COMMAND)


def test_every_command_that_takes_a_body_offers_fields() -> None:
    empty = {form.command for form in forms() if not form.fields}

    assert empty == GET_ONLY


def test_a_form_names_its_route_and_method() -> None:
    form = form_for("verify")

    assert form.command == "verify"
    assert form.route == ROUTE_FOR_COMMAND["verify"]
    assert form.method == "POST"


def test_a_command_with_no_body_is_a_get() -> None:
    assert form_for("doctor").method == "GET"
    assert form_for("doctor").fields == []


def test_an_image_field_is_offered_as_a_file() -> None:
    kinds = {field.name: field.kind for field in form_for("verify").fields}

    assert kinds["data"] == "file"


def test_a_list_of_images_is_offered_as_several_files() -> None:
    kinds = {field.name: field.kind for field in form_for("reads").fields}

    assert kinds["images"] == "files"


def test_a_flag_is_offered_as_a_checkbox() -> None:
    kinds = {field.name: field.kind for field in form_for("verify").fields}

    assert kinds["strict"] == "flag"


def test_a_number_is_offered_as_a_number() -> None:
    kinds = {field.name: field.kind for field in form_for("blank").fields}

    assert kinds["sides"] == "number"


def test_a_profile_field_carries_its_choices() -> None:
    field = next(entry for entry in form_for("hash").fields if entry.name == "profile")

    assert "release" in field.options


def test_every_kind_a_form_uses_is_one_the_page_knows() -> None:
    used = {field.kind for form in forms() for field in form.fields}

    assert used <= set(FIELD_KINDS)


def test_the_catalogue_serves_every_form(client: TestClient) -> None:
    body = client.get("/api/catalogue").json()

    assert len(body["forms"]) == len(forms())
    assert {entry["command"] for entry in body["forms"]} == set(ROUTE_FOR_COMMAND)


def test_a_required_field_is_marked() -> None:
    field = next(entry for entry in form_for("verify").fields if entry.name == "data")

    assert field.required


def test_a_field_with_a_default_is_not_required() -> None:
    field = next(entry for entry in form_for("verify").fields if entry.name == "strict")

    assert not field.required


def test_a_command_that_is_not_mapped_is_refused() -> None:
    with pytest.raises(KeyError):
        form_for("nonsense")


def test_a_handler_whose_only_hint_is_its_return_offers_no_fields() -> None:
    def handler() -> str:
        return ""

    assert model_for(handler) is None


def test_a_handler_with_a_plain_parameter_skips_it_and_finds_the_model() -> None:
    def handler(count: int, spec: ImageSpec) -> str:
        del count, spec
        return ""

    assert model_for(handler) is ImageSpec
