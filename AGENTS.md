# Working in this repository

[README.md](README.md) is the document written for a person, and it is the
source of truth for everything public: what each command does, how to run it,
and every figure the toolkit reports. [README.ja.md](README.ja.md) is the same
document in Japanese. Change the English one first, then the Japanese one, then
anything derived from either.

## What this project is, in one paragraph

An instrument for Famicom Disk System media: reading a disk, judging what came
back, reconstructing what Nintendo wrote, writing it again, and keeping the
drive that does all of that in adjustment. It reports measurements rather than
verdicts, and every claim it prints carries the basis it rests on. Where a
pleasant answer and an honest one pull apart, the honest one wins.

## The two surfaces

The command line and the local web page are two surfaces over one library. The
web layer decides nothing: every route parses its payload, calls the same
function the command calls, and reports what came back. A test compares the
route's answer against the command's answer for the same input, and a parity
test fails the build if a command is added without a route.

`fdstoolkit web` opens the page. There is no headless-only command, because the
toolkit drives hardware attached to this machine and is never a public service.

## What the measurements rest on

| Figure | Where it comes from |
|---|---|
| 96.4 kbit/s, ten percent either side | The rate the RAM adapter enforces. The only figure the hardware requires |
| 62, 93 and 124 counts at 6 MHz | A real FDSStick capture, ratio one to one and a half to two |
| 63.1, 27.9 and 9.0 percent pulse classes | The median of 120 real sides, gap runs stripped first |
| 36 percent undocumented opcodes | The median across 10,105 real program files |
| The formatted-blank disk info values | Measured across 1,729 never-rewritten sides |
| 142 of 144 corpus groups agree under `release` | A local set of 595 images |
| The FDSStick report numbers | Two independent tools that open `16D0:0AAA`: a Rust CLI and a Python reimplementation whose protocol notes come from disassembling the official binary, with per-item hardware confirmation |

Rotation speed is never used. Published figures for this mechanism disagree by
a factor of two and carry no tolerance.

## Things that look like bugs and are not

- A capture that carries pulse classes cannot measure speed, and the toolkit
  refuses rather than inventing timing. An FDSStick rounds every pulse in
  hardware, so this is the common case rather than an edge case.
- An FDSStick reports no drive state at all, so `DriveStatus` answers unknown
  and a destructive write refuses. `--assume-writable` clears the uncertainty,
  never a known fault.
- A drive that reaches one face at a time cannot select a side. Reading more
  than one side asks the operator to turn the disk over, and refuses rather
  than reading the same face twice.
- `SAVEDATA` and `JMP-TBL.` are reported by the opcode check and are working as
  intended. They are almost entirely non-code.
- The FDSStick driver speaks four reports and no more: `0x10` starts a transfer
  with a mode byte, `0x11` streams a read chunk, `0x12` carries a write chunk as
  an output report, `0x20` ends a write. Reports `0x01` through `0x09` drive the
  onboard SPI flash. They are never sent, because reading a disk does not need
  them and one published reading of `0x06` is a 64 KB block erase.
- Nothing in the hardware path has run against a device. Every driver test drives
  a recording stand-in, so it can prove which bytes we send and cannot prove the
  device accepts them.

## The gates

Every change passes all of these. A gate that was not run is a gate that
failed.

```bash
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest
```

Coverage is measured on every `pytest` run, not on request, and the floor is
100 percent of lines and branches. When a branch cannot be reached by any
input, delete it rather than excuse it.

Tests carry no comments and no section labels. Three blocks separated by one
blank line each, one call to the thing under test, and a name that states the
behaviour.

## Where things live

| Path | Holds |
|---|---|
| `core/` | The disk model, blocks, diagnostics, canonical identity |
| `codecs/` | fds, qd, raw, ares, mgd1, foreign-image rejection |
| `flux/` | Capture readers, pulse-family fitting, decoding |
| `drive/` | Speed, stability, bracketing, fault classification, advice |
| `quality/` | Reads, confidence, grading, calibration, the surface test |
| `master/` | Corpus consensus, splicing, reference sets |
| `submit/` | The dump log and the submission report |
| `ui/` | The web surface: routes, schemas, derived forms, static page |
| `cli/` | One module per command family, each with a `register(app)` |

`cli/common.py` holds what more than one command family needs. A helper used
twice belongs there rather than being copied.

## What this cannot do

No flux capture of a Disk System disk exists anywhere. Quick Disk is one
continuous spiral with no index hole and no stepping, so KryoFlux and
Greaseweazle cannot read this medium. The readers for those formats exist to
validate the measurement layer against bytes the toolkit did not generate
itself, and doing so found four real defects.

Head alignment is not measurable from timing. Belt and motor faults are not
separable without the pulley ratio, which no trustworthy source states. Both
are named in the README rather than guessed at.
