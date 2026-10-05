from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate_licensees.py"
ENOUGH = 120


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_licensees", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enum_source(members: list[tuple[str, int]]) -> str:
    body = "\n".join(f"            {name} = 0x{code:02X}," for name, code in members)
    return (
        "namespace Demo\n{\n    public class Info\n    {\n"
        "        public enum Company\n        {\n"
        f"{body}\n"
        "        }\n\n        public enum Other\n        {\n            Late = 0x02,\n        }\n"
        "    }\n}\n"
    )


def companies(count: int) -> list[tuple[str, int]]:
    return [(f"Company{code:03d}", code) for code in range(1, count + 1)]


def test_every_company_is_read_by_its_hex_code() -> None:
    table_of: Callable[[str], dict[str, str]] = load_script().company_table

    table = table_of(enum_source(companies(ENOUGH)))

    assert len(table) == ENOUGH
    assert table["0x01"] == "Company001"
    assert table["0x78"] == "Company120"


def test_members_of_a_later_enum_are_left_out() -> None:
    table_of: Callable[[str], dict[str, str]] = load_script().company_table

    table = table_of(enum_source(companies(ENOUGH)))

    assert "Late" not in table.values()


def test_a_code_named_twice_is_refused() -> None:
    table_of: Callable[[str], dict[str, str]] = load_script().company_table
    members = [*companies(ENOUGH), ("Again", 0x01)]

    with pytest.raises(ValueError, match=r"code 0x01 is named twice, Company001 and Again"):
        table_of(enum_source(members))


def test_a_table_too_short_to_be_the_real_one_is_refused() -> None:
    table_of: Callable[[str], dict[str, str]] = load_script().company_table

    with pytest.raises(ValueError, match=r"read only 3 companies"):
        table_of(enum_source(companies(3)))


def test_a_source_without_the_enum_is_refused() -> None:
    table_of: Callable[[str], dict[str, str]] = load_script().company_table

    with pytest.raises(ValueError, match=r"expected one Company enum, found 0"):
        table_of("namespace Demo {}\n")


def test_the_script_writes_the_table_with_its_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "FdsBlockDiskInfo.cs"
    source.write_text(enum_source(companies(ENOUGH)), encoding="utf-8")
    output = tmp_path / "licensees.json"
    arguments = [str(SCRIPT), str(source), "--commit", "abc123", "--version", "9.9.9"]
    monkeypatch.setattr(sys, "argv", [*arguments, "--output", str(output)])

    code = load_script().main()

    document = json.loads(output.read_text(encoding="utf-8"))
    assert code == 0
    assert document["package"] == "nes-containers 9.9.9"
    assert document["source"].endswith("/blob/abc123/FdsBlockDiskInfo.cs")
    assert len(document["sha256"]) == 64
    assert len(document["licensees"]) == ENOUGH
