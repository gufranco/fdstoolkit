from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path

SCRIPT_NAME: Final = "index-built.js"
STYLE_NAME: Final = "index-built.css"
ASSETS: Final = (f"assets/{SCRIPT_NAME}", f"assets/{STYLE_NAME}")
BUILT_MARKUP: Final = (
    '<!doctype html>\n<html lang="en">\n<head>\n'
    f'<script type="module" crossorigin src="/static/assets/{SCRIPT_NAME}"></script>\n'
    f'<link rel="stylesheet" crossorigin href="/static/assets/{STYLE_NAME}">\n'
    '</head>\n<body>\n<div id="root"></div>\n</body>\n</html>\n'
)


def built_page(root: Path) -> Path:
    page = root / "page"
    (page / "assets").mkdir(parents=True)
    (page / "index.html").write_text(BUILT_MARKUP, encoding="utf-8")
    (page / ASSETS[0]).write_text("export {};\n", encoding="utf-8")
    (page / ASSETS[1]).write_text("body {}\n", encoding="utf-8")
    return page
