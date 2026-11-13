from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

TESTS = Path(__file__).resolve().parent.parent
MARKERS = ("Arrange", "Act", "Assert")
JS_CASE = re.compile(r"^\s*(?:it|test)\(")
JS_MARKER = re.compile(r"^\s*// (\w+)$")
DIRECTIVES = ("# noqa", "# type:", "# pyright:")


def python_markers(path: Path) -> dict[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    comments = [
        (token.start[0], token.string)
        for token in tokenize.generate_tokens(io.StringIO(text).readline)
        if token.type == tokenize.COMMENT and not token.string.startswith(DIRECTIVES)
    ]
    found: dict[str, list[str]] = {}
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test"
        ):
            span = range(node.lineno, (node.end_lineno or node.lineno) + 1)
            found[f"{path.name}::{node.name}"] = [
                comment for line, comment in comments if line in span
            ]
    return found


def javascript_markers(path: Path) -> dict[str, list[str]]:
    lines = path.read_text(encoding="utf-8").split("\n")
    found: dict[str, list[str]] = {}
    for start, line in enumerate(lines):
        if not JS_CASE.match(line) or not line.rstrip().endswith("{"):
            continue
        depth, end = line.count("{") - line.count("}"), start + 1
        while depth > 0 and end < len(lines):
            depth += lines[end].count("{") - lines[end].count("}")
            end += 1
        found[f"{path.name}:{start + 1}"] = [
            match.group(1) for body in lines[start:end] if (match := JS_MARKER.match(body))
        ]
    return found


def test_every_python_test_opens_its_three_blocks_with_bare_markers() -> None:
    # Arrange
    paths = sorted(TESTS.rglob("test_*.py"))

    # Act
    found = {name: markers for path in paths for name, markers in python_markers(path).items()}

    # Assert
    expected = [f"# {marker}" for marker in MARKERS]
    assert {name: markers for name, markers in found.items() if markers != expected} == {}


def test_every_page_test_opens_its_three_blocks_with_bare_markers() -> None:
    # Arrange
    paths = [*sorted((TESTS / "web").glob("*.test.js")), *sorted((TESTS / "e2e").glob("*.js"))]

    # Act
    found = {name: markers for path in paths for name, markers in javascript_markers(path).items()}

    # Assert
    assert found
    assert {name: markers for name, markers in found.items() if markers != list(MARKERS)} == {}


def test_no_python_file_names_typing_any() -> None:
    # Arrange
    roots = (TESTS.parent / "src", TESTS)

    # Act
    found = [
        f"{path.name}:{node.lineno}"
        for root in roots
        for path in sorted(root.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Name | ast.alias)
        and getattr(node, "id", getattr(node, "name", "")) == "Any"
    ]

    # Assert
    assert found == []
