from __future__ import annotations

import pytest
from pydantic import ValidationError

from fdstoolkit.hardware.session import MAX_RETRIES
from fdstoolkit.ui.history_schemas import LogSpec, SessionSpec

LABEL_LIMIT = 64


def test_a_drive_label_longer_than_the_limit_is_refused() -> None:
    # Arrange
    label = "x" * (LABEL_LIMIT + 1)

    # Act
    with pytest.raises(ValidationError) as raised:
        LogSpec.model_validate({"drive": label})

    # Assert
    assert raised.value.errors()[0]["loc"] == ("drive",)


def test_a_session_check_retries_within_the_dump_limit() -> None:
    # Arrange
    retries = MAX_RETRIES + 1

    # Act
    with pytest.raises(ValidationError) as raised:
        SessionSpec.model_validate({"retries": retries})

    # Assert
    assert raised.value.errors()[0]["loc"] == ("retries",)


def test_a_session_check_needs_nothing_by_default() -> None:
    # Arrange
    expected = (None, 3)

    # Act
    spec = SessionSpec.model_validate({})

    # Assert
    assert (spec.reference, spec.retries) == expected
