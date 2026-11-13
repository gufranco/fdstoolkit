# Working in this repository

The public documentation is two documents written for a person, and together
they are the source of truth for everything public. [README.md](README.md) is a
short guide: install, the command index, the procedures, the web page and what
the toolkit cannot do. [REFERENCE.md](REFERENCE.md) holds what each command
does, how to run it, and every figure the toolkit reports.
[README.ja.md](README.ja.md) and [REFERENCE.ja.md](REFERENCE.ja.md) are the same
documents in Japanese. Change the English one first, then the Japanese one, then
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

- An FDSStick capture carries pulse classes, never timing. `calibrate speed`
  still finds a drive outside the tolerance, by comparing each class against
  what an image of the same disk requires: a class read short means fast, long
  means slow. A drive a percent off misreads no class, so the fine band is left
  to a console speed test or a strobe, and the README says so.
- A drive that reads back its own writes proves nothing about the drive, since a
  drive out of adjustment writes disks only it can read. Calibration is judged
  against a disk this drive did not write, and the command prints that first.
- An FDSStick reports no drive state at all, so `DriveStatus` answers unknown.
  Unknown does not block a write; a state the drive reports as bad does. The
  safety of a write comes from the backup, the confirmation and the readback
  comparison, not from a status the stick cannot give.
- A disk physically has two sides, so an image of more than two is refused, even
  though the file format and FDSPacker's own fixtures allow more. The refusal
  states that physical reason.
- Disk images are `.fds` and `.qd`, and nothing else. `raw03` captures and
  IPS, UPS and BPS patches are read because neither is a disk image.
- A drive that reaches one face at a time cannot select a side. Reading more
  than one side asks the operator to turn the disk over, and refuses rather
  than reading the same face twice.
- An FDSStick does two jobs. It is an interface between a real Disk System drive
  and this machine, and it is a drive emulator that plays images off its own
  flash. Only the first is in scope, so the driver speaks three reports and no
  more: `0x10` starts a transfer and carries the mode, `0x11` streams a read
  chunk, `0x12` carries a write chunk as an output report, and `0x20` with a
  zero byte finishes a physical write.
- Reports `0x01` through `0x09` drive the onboard SPI flash, and `0x21` through
  `0x23` drive the emulator. Neither group is ever sent. A read does not need the
  flash, and one published reading of `0x06` is a 64 KB block erase.
- The write stream follows the one captured write of the official tool, as
  fdsstick-cli documents it from a USB capture of `fdsstick_20160926.exe`: a
  `C0 00 AB` header, then one value from 1 to 3 per data bit, packed four to a
  byte, and `0x20 00` after the data. The stick plays the four values of a byte
  lowest bits first, and the bits of each data byte lowest first. A one is value
  1, a zero after a one is 3, and a zero after a zero is 2. The lengths between
  blocks are not the tool's: they come from factory sides read through this
  toolkit, and `codecs/write_stream.py` builds each side bit by bit to meet
  them. An 18,000-bit lead-in puts the first block where a factory side has it,
  999-bit gaps read back as 1,005 bits, and after the last block a run of 976 to
  978 zero bits, set by the last two bits of its checksum, reads back as the
  factory's 976, followed by the factory fill: the bits 1, 1, 0, 1, five zeros,
  then 1, 1, 0 repeated. Blank packets carry on that fill as `75 5D D7`. The
  official tool sends `0x20 00` once after the last side; this driver sends it
  after every side, because it reads each side back before writing the next. An
  earlier reading took `0x20 00` for an emulator eject; the capture shows the
  official tool sending it to finish a physical write. A write is always
  preceded by a read of the same side in the same session: two of four writes
  that a script started without one stopped partway through the image, leaving a
  half-written side.
- The report map changed between firmware generations. A console app that opened
  this same device in 2015 started a read with `0x11` and took data from `0x12`,
  with separate `0x13` and `0x14` for writing and no mode byte anywhere. The two
  tools tested against a unit in 2026 start with `0x10` plus a mode byte and read
  from `0x11`. The whole map is shifted by one. This driver speaks the later one,
  and a read that comes back empty says so rather than reporting a dead disk.
- A read often opens with a stale reply carrying the sequence number of an earlier
  read, and the next packet is then numbered `2`: the stale reply takes the first
  packet's slot. It is dropped, and the read expects `2` next, so it is not
  reported as a skipped packet.
- The sequence counter wraps with an add, so `0xFF` is followed by `0x00`. Mapping
  it back to `1` aborts every side, because 255 chunks carry 64,770 bytes and a
  gapped side is about 66,560.
- A block opens with the mark `0x80`, written low bit first: seven zero bits that
  end the gap, then the one that is the first pulse after it. Decoding starts at
  that pulse with the seven zeros already taken, and the encoder writes each gap
  and its mark as one stream.
- `tests/fixtures/fdsstick/` holds a real read of the calibration side, written and
  read back by an FDSStick on firmware 3.12. The decoder must recover it exactly,
  the encoder must reproduce its pulses, and calibration must read it clean.
- A block cut short, by a USB packet lost inside it for one, makes the decoder
  read on through the gap behind it to collect the bits the block declares. After
  a block fails its checksum, decoding resumes at the first gap past the block's
  start where a block that passes its checksum begins.
- Real reads carry pulses that fit no class before the first block, 19 to 525 a
  read, and in the splice 18 to 79 values after a block ends, never inside a
  block that read clean; a side read whole also carries a few past its last
  declared block, at the same places on every read, where older recordings
  remain. Noise is therefore counted from the first block to the last declared
  one, except 16 to 160 values after each block. A side missing blocks is
  counted to the end of the read, and a read where no block frames counts every
  such pulse, so the noisiest line still warns.
- hidapi on macOS answers a write the stick did not take with -1 after five
  seconds instead of raising. A refused packet is sent once more and never
  skipped past. Every side written from blocks is padded with gap to 700
  packets; the stick stops taking data where the track ends, 568 packets in
  three runs on one drive. Refused twice inside the image is a link fault that
  says how much was written, and refused in the padding means the side ended.
  The first read after a finished write is refused while the
  drive settles, seen up to 6.6 s after the finish and sometimes after a stale
  first reply. A write started after a read is refused inside its lead-in until
  the drive has finished its scan: on a short side it failed with a pause of up
  to 8 s after the read and went through after 12 s. A refusal can take 5 s or
  return at once, so both are retried on time rather than on attempts: up to
  eight tries 2 s apart, each in its own watchdog window. A write refused inside
  the lead-in has written no block, so the whole session starts again. A
  transport error on a read or a write becomes a link fault, which every caller
  reports, and a read that fails after it kept data is never retried.
- The stick erases nothing past the last packet it is sent, so without the gap
  padding a side written over a longer one kept the old blocks after its own,
  and another reader would take them for a hidden file. `write` still fails its
  verification over any such block, and the surface test judges only the blocks
  it wrote.
- Every real read carries 1,000 to 1,500 stray pulses in its first 3,700
  values while the drive settles, and a burst among them can frame a false
  block. Decoding starts at the first disk information block that passes its
  checksum, and the lead-in is the gap before it; a side with no such block is
  decoded from its first value.
- The mode byte after `0x10` is `00` for a read and `01` for a write, and no
  source gives any other value a meaning. On firmware 3.12 a read started with
  `02` ended in a read error and damaged a 24 KB file data block of the side,
  so the driver sends no other value. Pulse timing comes from the firmware: the
  FDSStick's author shows it from his own debug program, and `calibrate`
  measures it from any read whose bytes are pulse counts rather than classes.
- hidapi on macOS binds to the thread that makes its first call, and cleaning up at
  exit crashes with SIGTRAP when that thread is gone. `fdstoolkit web` therefore
  makes the first call on the main thread before it serves. Every USB call of one
  side runs in one supervised thread: a thread per packet left gaps of up to 25 ms
  in a web write, and the stick refused the rest of the side. A side that
  overruns its deadline is reported at once, but the device is closed by that
  same thread when the hung call returns: hidapi does not allow closing a device
  while another thread is inside a call on it.
- The read and write paths have run against one FDSStick on firmware 3.12. Every
  other driver test drives a recording stand-in, which proves which bytes we send
  and not that a device accepts them.

## Hard rules

Every disk write stays inside the factory layout, as measured on factory sides:
gaps of 982 to 1,055 bits between blocks, a run of 975 or 976 bits after the
last block, and the factory fill to the end of the track. `factory_violations`
in `codecs/write_stream.py` checks a stream against those ranges, and a test
runs every kind of side through the encoder and fails the build on any
violation. A change that moves a write outside them is not done. The first
block's position is judged as an average over writes, never by one read: the
drive turns ready at a point that moves by hundreds of bits each time it spins
up, on factory disks too, and the stick holds the first packet until ready,
about 2.4 s, then plays one packet every 10 to 11 ms, so the stream cannot shift
it. Ten writes of the 18,000-bit lead-in averaged 17,337 bits against 17,229 for
the two factory sides measured. The duplicator's noise after each block and
before the lead-in is a by-product, not part of the layout, and is never
imitated.

## The gates

Every change passes all of these. A gate that was not run is a gate that
failed.

```bash
uv run ruff format .
uv run ruff check .
uv run pyright
uv run pytest
pnpm test:coverage
pnpm e2e
pnpm format:check
uv run yamllint --strict .
```

Coverage is measured on every `pytest` run, not on request, and the floor is
100 percent of lines and branches. The page script carries the same floor
under `pnpm test:coverage`. When a branch cannot be reached by any input,
delete it rather than excuse it.

`pnpm e2e` drives the page in Chromium against a simulated two-sided drive
served by `tests/e2e/serve.py`, at desktop width and at 320 pixels. It checks
what only a browser can answer: every control is at least 44 pixels tall, the
erase dialog is modal and starts on a visible Cancel, and nothing overflows.
The first run needs `pnpm exec playwright install chromium`. A change to the
page is not done until this suite passes.

Every test has three blocks, each opened by its bare marker, `# Arrange`,
`# Act` and `# Assert`, or `// Arrange`, `// Act` and `// Assert` in the page
and browser tests, and separated by one blank line each. The markers are the
only comments a test carries. The Act block makes one call to the thing under
test, and the name states the behaviour.

## Where things live

| Path | Holds |
|---|---|
| `core/` | The disk model, blocks, diagnostics, canonical identity |
| `codecs/` | fds, qd, the raw03 pulse classes, foreign-image rejection |
| `drive/` | Live calibration of the drive against a reference disk |
| `quality/` | Reads, confidence, grading, the surface test |
| `identify/` | Digests and provenance |
| `master/` | Splicing a good block in from another dump |
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

Fine head alignment is not measurable from pulse classes; `calibrate head` sees
only which blocks read. Belt and motor faults are not separable without the
pulley ratio, which no trustworthy source states. Both are named in the README
rather than guessed at.
