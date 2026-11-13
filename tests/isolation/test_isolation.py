from __future__ import annotations

import importlib

import pytest


def test_the_real_hid_module_is_out_of_reach_of_ordinary_tests() -> None:
    # Arrange
    name = "hid"

    # Act
    with pytest.raises(ImportError) as raised:
        importlib.import_module(name)

    # Assert
    assert raised.type is ModuleNotFoundError
