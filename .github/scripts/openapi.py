from __future__ import annotations

import json
import sys

from fdstoolkit.ui.app import create_app


def main() -> None:
    sys.stdout.write(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
