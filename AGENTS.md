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
| 63.1, 27.9 and 9.0 percent pulse classes | The median of 120 real sides, gap runs stripped first |
| 36 percent undocumented opcodes | The median across 10,105 real program files |
| The formatted-blank disk info values | Measured across 1,729 never-rewritten sides |
| 142 of 144 corpus groups agree under `release` | A local set of 595 images |
| The FDSStick report numbers | Two independent tools that open `16D0:0AAA`: a Rust CLI and a Python reimplementation whose protocol notes come from disassembling the official binary, with per-item hardware confirmation |

Rotation speed is never used. Published figures for this mechanism disagree by
a factor of two and carry no tolerance.

## Things that look like bugs and are not

- An FDSStick capture carries pulse classes, never timing, so no command
  measures speed from one. Speed comes only from the console through
  `calibrate --cycles`, and the timing commands that once read other capture tools'
  output are gone.
- An FDSStick reports no drive state at all, so `DriveStatus` answers unknown.
  Unknown does not block a write; a state the drive reports as bad does. The
  safety of a write comes from the backup, the confirmation and the readback
  comparison, not from a status the stick cannot give.
- Every game uses at most one disk, with one or two sides. No game spans a
  second disk.
- Disk images are `.fds` and `.qd`, and nothing else. `raw03` captures and
  IPS, UPS and BPS patches are read because neither is a disk image.
- A drive that reaches one face at a time cannot select a side. Reading more
  than one side asks the operator to turn the disk over, and refuses rather
  than reading the same face twice.
- `SAVEDATA` and `JMP-TBL.` are reported by the opcode check and are working as
  intended. They are almost entirely non-code.
- An FDSStick does two jobs. It is an interface between a real Disk System drive
  and this machine, and it is a drive emulator that plays images off its own
  flash. Only the first is in scope, so the driver speaks three reports and no
  more: `0x10` starts a transfer and carries the mode, `0x11` streams a read
  chunk, `0x12` carries a write chunk as an output report.
- Reports `0x01` through `0x09` drive the onboard SPI flash, and `0x20` through
  `0x23` drive the emulator. Neither group is ever sent. A read does not need the
  flash, one published reading of `0x06` is a 64 KB block erase, and `0x20` with
  a zero byte ejects an emulated disk rather than finishing a physical write.
- How a physical write ends is unknown. The one set of notes taken from the
  official binary lists the write-to-adapter terminator and its acknowledgement
  as never traced, so the driver streams the side and stops.
- The report map changed between firmware generations. A console app that opened
  this same device in 2015 started a read with `0x11` and took data from `0x12`,
  with separate `0x13` and `0x14` for writing and no mode byte anywhere. The two
  tools tested against a unit in 2026 start with `0x10` plus a mode byte and read
  from `0x11`. The whole map is shifted by one. This driver speaks the later one,
  and a read that comes back empty says so rather than reporting a dead disk.
- The sequence counter wraps with an add, so `0xFF` is followed by `0x00`. Mapping
  it back to `1` aborts every side, because 255 chunks carry 64,770 bytes and a
  gapped side is about 66,560.
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
| `codecs/` | fds, qd, the raw03 pulse classes, foreign-image rejection |
| `drive/` | The pulse-class reading and the console speed reading |
| `quality/` | Reads, confidence, grading, calibration, the surface test |
| `master/` | Corpus consensus, splicing, reference sets |
| `ui/` | The web surface: routes, schemas, derived forms, static page |
| `cli/` | One module per command family, each with a `register(app)` |

`cli/common.py` holds what more than one command family needs. A helper used
twice belongs there rather than being copied.

## What this cannot do

No flux capture of a Disk System disk exists anywhere. Quick Disk is one
continuous spiral with no index hole and no stepping, so KryoFlux and
Greaseweazle cannot read this medium. Readers for their formats once lived here
to validate the measurement layer against bytes the toolkit did not generate,
and found four real defects before they were removed with every other path
that needs hardware other than the FDSStick.

Head alignment is not measurable from pulse classes. Belt and motor faults are not
separable without the pulley ratio, which no trustworthy source states. Both
are named in the README rather than guessed at.
