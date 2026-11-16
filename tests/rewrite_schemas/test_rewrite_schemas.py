from __future__ import annotations

import pytest
from pydantic import ValidationError

from fdstoolkit.ui.rewrite_schemas import EraseSpec


def test_an_erase_takes_one_or_two_sides() -> None:
    # Arrange
    payload = {"sides": 3, "confirm": True}

    # Act
    with pytest.raises(ValidationError) as raised:
        EraseSpec.model_validate(payload)

    # Assert
    assert raised.value.errors()[0]["loc"] == ("sides",)


def test_an_erase_defaults_to_one_side_unconfirmed() -> None:
    # Arrange
    payload: dict[str, object] = {}

    # Act
    spec = EraseSpec.model_validate(payload)

    # Assert
    assert (spec.sides, spec.confirm, spec.retries) == (1, False, 3)
