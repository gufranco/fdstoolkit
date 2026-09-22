## What this changes

<!-- One paragraph. What a reader of the diff would not work out on their own. -->

## How it was established

<!-- For anything asserted about the hardware, the disk format or an emulator:
say what was run or read, not what was reasoned. Several findings in this
project reversed under measurement. -->

## Checklist

- [ ] `uv run ruff format --check .` and `uv run ruff check .` pass
- [ ] `uv run pyright` passes
- [ ] `uv run pytest --cov` passes at 100%, on a clean checkout with no disk images present
- [ ] No disk image, BIOS, firmware or save data added, in any form
- [ ] Nothing added that points at where to obtain those files
- [ ] Any new claim about hardware is marked unconfirmed in `docs/provenance.md`, or carries what was run
