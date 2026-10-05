from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Final

SOURCE_URL: Final = "https://github.com/ClusterM/nes-containers/blob/{commit}/FdsBlockDiskInfo.cs"
ENUM_START: Final = re.compile(r"public enum Company\b")
ENUM_END: Final = re.compile(r"^\s*}\s*$")
MEMBER: Final = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*0x([0-9A-Fa-f]{1,2})\s*,?\s*$")
BODY_OFFSET: Final = 2
EXPECTED_MIN: Final = 100


def company_table(text: str) -> dict[str, str]:
    lines = text.splitlines()
    starts = [index for index, line in enumerate(lines) if ENUM_START.search(line)]
    if len(starts) != 1:
        message = f"expected one Company enum, found {len(starts)}"
        raise ValueError(message)
    table: dict[str, str] = {}
    for line in lines[starts[0] + BODY_OFFSET :]:
        if ENUM_END.match(line):
            break
        match = MEMBER.match(line)
        if match is None:
            continue
        name, code = match.groups()
        key = f"0x{int(code, 16):02X}"
        if key in table:
            message = f"code {key} is named twice, {table[key]} and {name}"
            raise ValueError(message)
        table = {**table, key: name}
    if len(table) < EXPECTED_MIN:
        message = f"read only {len(table)} companies, the enum layout may have changed"
        raise ValueError(message)
    return dict(sorted(table.items()))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Write FDSPacker's licensee names from nes-containers' FdsBlockDiskInfo.cs."
    )
    parser.add_argument("source", type=Path, help="FdsBlockDiskInfo.cs from a nes-containers clone")
    parser.add_argument("--commit", required=True, help="the nes-containers commit it came from")
    parser.add_argument("--version", required=True, help="the nes-containers package version")
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()

    raw: bytes = options.source.read_bytes()
    licensees = company_table(raw.decode("utf-8-sig"))
    document = {
        "version": 1,
        "source": SOURCE_URL.format(commit=options.commit),
        "package": f"nes-containers {options.version}",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "licensees": licensees,
    }
    output: Path = options.output
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    sys.stdout.write(f"wrote {len(licensees)} licensees to {output}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
