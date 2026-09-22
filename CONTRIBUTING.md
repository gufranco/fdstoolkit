# Contributing

## Getting it running

```bash
git clone https://github.com/gufranco/fdstoolkit.git
cd fdstoolkit
uv sync --all-extras --dev
uv run pytest
```

The suite passes on a clean checkout with no disk images and no BIOS present.
That is deliberate and CI enforces it: anybody has to be able to work on this
without owning a collection. The tests that want real images read the directory
named by `FDSTOOLKIT_CORPUS` and skip when it is unset.

## The gates

| Gate | Command |
|------|---------|
| Format | `uv run ruff format --check .` |
| Lint | `uv run ruff check .` |
| Types | `uv run pyright` |
| Tests | `uv run pytest --cov` |

Coverage is gated at 100%, statements and branches. A line that genuinely cannot
run carries a coverage directive naming why; everything else gets a test. The
reason for 100% rather than a high number: this toolkit writes to physical media
and tells you whether a dump is trustworthy, and a branch nobody exercised is a
branch whose first run happens against somebody's only copy of a disk.

## Things this project will not accept

**No disk image, BIOS, firmware or save data, in any form.** Not as a test
fixture, not base64 encoded, not a small one. Tests generate their own disks.
This is the one rule with no exceptions.

**No link or hint pointing at where to obtain those files.** The documentation
describes how to confirm a file you already have is the right one. It does not
help anybody find it.

**No claim that has not been checked.** If a change asserts something about the
hardware or the format, say what was run or read. Several findings here reversed
under measurement: the save is not the last file on the side, the approval file
is not recognised by its name, and masking the country byte alone closes no gap.
Each of those was believed until somebody counted.

## Hardware claims

Nothing in this project has touched a real drive. Anything asserted about the
FDSStick, the Famicom Dumper or a disk drive is read from a source and marked as
unconfirmed in `docs/provenance.md`. A change that turns one of those into a
verified claim is the most valuable kind of contribution here, and it belongs in
that table with what was run.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/). The release is cut
by semantic-release from the commit history, so the type prefix decides the
version. `feat` gives a minor, `fix` gives a patch, and a `BREAKING CHANGE:`
footer gives a major.

## Tests

Tests are named for the behaviour they check rather than the function they call,
and each one has a single act. If a test needs a comment to be understood, the
test is doing too much.

A bug fix ships with a test that fails without the fix.
