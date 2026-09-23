from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

FORMULA = Path("Formula/fdstoolkit.rb")
SELF = "fdstoolkit"


def resources() -> set[str]:
    return set(re.findall(r'^\s*resource "([^"]+)" do', FORMULA.read_text(), re.MULTILINE))


def closure() -> set[str]:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not on the path here")
    exported = subprocess.run(
        [
            uv,
            "export",
            "--all-extras",
            "--no-dev",
            "--no-hashes",
            "--no-emit-project",
            "--format",
            "requirements-txt",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if exported.returncode:
        pytest.skip("uv could not export the runtime closure here")
    found = {
        line.partition("==")[0].strip()
        for line in exported.stdout.splitlines()
        if "==" in line and not line.startswith("#")
    }
    return found - {SELF}


def test_the_formula_carries_every_runtime_dependency() -> None:
    assert closure() - resources() == set()


def test_the_formula_carries_no_resource_nothing_needs() -> None:
    assert resources() - closure() == set()


def test_every_resource_pins_a_checksum() -> None:
    text = FORMULA.read_text()
    names = re.findall(
        r'^\s*resource "([^"]+)" do\n\s*url "[^"]+"\n\s*sha256 "([0-9a-f]{64})"', text, re.MULTILINE
    )

    assert len(names) == len(resources())


def test_the_hardware_library_is_a_dependency() -> None:
    assert 'depends_on "hidapi"' in FORMULA.read_text()


def test_the_rust_toolchain_is_a_build_dependency() -> None:
    assert 'depends_on "rust" => :build' in FORMULA.read_text()


def test_the_test_block_proves_the_hardware_and_the_page() -> None:
    text = FORMULA.read_text()

    assert "import hid, fastapi, uvicorn, pydantic" in text
    assert "hidapi is installed" in text
    assert "fdstoolkit web --help" in text
