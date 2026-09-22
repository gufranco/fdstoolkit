# fdstoolkit

Command line tools for Famicom Disk System disk images: convert between formats, verify structure and checksums, identify images against a DAT, edit and repair them, prepare them for emulators and flash carts, and dump or write real disks through supported hardware.

[![ci](https://github.com/gufranco/fdstoolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/gufranco/fdstoolkit/actions/workflows/ci.yml)
[![analysis](https://github.com/gufranco/fdstoolkit/actions/workflows/analysis.yml/badge.svg)](https://github.com/gufranco/fdstoolkit/actions/workflows/analysis.yml)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

```console
$ fdstoolkit info "Falsion (Japan).fds"
Falsion (Japan).fds: fds container, 2 side(s), 131000 bytes
  side 0: FAL files=6 hidden=0 rewrites=0
  side 1: FAL files=10 hidden=0 rewrites=0

$ fdstoolkit diff "Falsion (Japan).fds" "Falsion (Japan).qd" --explain
same software, 6 provenance field(s) differ
  side 0 manufacturing_date (provenance): 1987-10-09 against 1987-09-22
  side 0 rewritten_date (provenance): 1987-10-09 against ffffff

$ fdstoolkit canon "Falsion (Japan).qd" --profile release
fdstoolkit:v1:release/v1:826f23fad684f7acdb59b0132c4714e080f80e7a63e19cbce8a964e384fc1186
```

## Install

```bash
brew tap gufranco/fdstoolkit https://github.com/gufranco/fdstoolkit
brew install gufranco/fdstoolkit/fdstoolkit
```

With [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/gufranco/fdstoolkit
```

The hardware commands need the `hardware` extra, which pulls in hidapi:

```bash
uv tool install 'fdstoolkit[hardware] @ git+https://github.com/gufranco/fdstoolkit'
```

Check the installation with `fdstoolkit doctor`. It prints the version, the interpreter, the platform, whether hidapi is present, whether an FDSStick is connected, and the DAT cache location.

Requires Python 3.12 or newer. Runs on macOS, Linux and Windows.

## Commands

Every command that produces a report accepts `--json`. The exit code is 0 when nothing failed and 1 when something did.

### Inspecting

| Command | Output |
|---|---|
| `fdstoolkit info IMAGE` | Side count, game code, dates, rewrite count, file counts, hidden files |
| `fdstoolkit ls IMAGE` | Every file with name, load address, kind, size, hidden flag |
| `fdstoolkit verify IMAGE` | Structural and checksum findings. `--strict` fails on warnings |
| `fdstoolkit hash IMAGE` | CRC32, MD5, SHA-1, SHA-256, per side, canonical digest, RetroAchievements MD5 |
| `fdstoolkit provenance IMAGE` | Factory or kiosk rewrite, dates, Disk Writer serial, rewrite count, disk colour |
| `fdstoolkit boot IMAGE` | What the console does with each side, and the BIOS error it would show |
| `fdstoolkit layout IMAGE` | File offsets on the side, and the time the drive spends reaching them |
| `fdstoolkit diff A B` | Which blocks differ. `--explain` names the fields and files instead |

### Converting and creating

| Command | Output |
|---|---|
| `fdstoolkit convert IMAGE -o OUT` | Between `.fds` and `.qd`. `--header`, `--crc-mode` |
| `fdstoolkit canon IMAGE --profile P` | Canonical digest, and the canonical image with `-o` |
| `fdstoolkit blank -o OUT --sides N` | Blank image. `--formatted` writes a disk information block |
| `fdstoolkit build MANIFEST -o OUT` | A disk built from a JSON manifest |
| `fdstoolkit card -o OUT` | A blank an FDSKey card accepts. `--firmware released` |
| `fdstoolkit split IMAGE -d DIR` | One file per side, in copier layout |
| `fdstoolkit join FILES -o OUT` | Side files back into one image, in any argument order |
| `fdstoolkit merge DISK1 DISK2 -o OUT` | The disks of a multi-disk game into one image |
| `fdstoolkit unmerge SET -d DIR` | A merged image back into one file per disk |
| `fdstoolkit export IMAGE --target T -d DIR` | The layout a device expects. `--bios` places the BIOS too |
| `fdstoolkit import-ares FILES -o OUT` | An image from ares side files, including its save |

### Editing and repairing

| Command | Output |
|---|---|
| `fdstoolkit extract IMAGE -d DIR` | Every file to disk, hidden ones included |
| `fdstoolkit insert IMAGE --file F --name N -o OUT` | Adds a file and raises the declared count |
| `fdstoolkit set IMAGE --set field=value -o OUT` | Changes disk information fields |
| `fdstoolkit clean IMAGE -o OUT` | Removes bytes after the last block |
| `fdstoolkit rebuild IMAGE -o OUT` | Recomputes checksums, corrects declared sizes, drops trailing data |
| `fdstoolkit patch IMAGE --patch P -o OUT` | Applies IPS, UPS or BPS, with or without a header |

`rebuild` keeps hidden files by default. `--reveal-hidden` raises the declared count to the number of files present, `--drop-hidden` removes them, `--keep-tail` leaves trailing data alone, and `--renumber` renumbers the file headers.

### Saves

| Command | Output |
|---|---|
| `fdstoolkit saves A B ...` | Compares dumps of one release and reports which file holds the save |
| `fdstoolkit save-apply IMAGE --save S -o OUT` | Merges an IPS, UPS or BPS save, or a whole image |
| `fdstoolkit save-extract IMAGE --played P -o OUT` | Writes the difference as a save. `--format ips\|ups\|image` |
| `fdstoolkit normalise-saves IMAGE -o OUT` | Blanks a save area from a declared recipe |

### Measuring quality

| Command | Output |
|---|---|
| `fdstoolkit flux CAPTURE` | Bit cell, cluster separation, jitter, speed and outliers from a flux capture |
| `fdstoolkit flux-decode CAPTURE -o OUT` | An image decoded from a capture, fitting its thresholds to the data |
| `fdstoolkit reads A B ...` | Which blocks move across repeated dumps of one disk, and in which direction |
| `fdstoolkit grade IMAGE` | A grade with the measurement behind it. `--read`, `--margin`, `--map` |
| `fdstoolkit calibrate REF --read R` | The drive's own error rate, so a disk is not blamed for it |
| `fdstoolkit integrity IMAGE` | An image that passes its checksums and is still wrong |

The opcode check is calibrated against 10,105 program files: a real one is around a third undocumented opcodes, because these files routinely carry data as well as code, so only a file that is almost entirely non-code is reported. Names like `SAVEDATA` and `JMP-TBL.` turn up that way and are working as intended.

`flux` reads SuperCard Pro `.scp`, KryoFlux streams, HxC `.hfe`, and the interval captures an FDSStick produces. The format is detected from the file; `--format` overrides it.

The pulse family is detected too. A Disk System or MFM stream runs on intervals of 1, 1.5 and 2 cells; a group-coded stream runs on 1, 2 and 3. Fitting the wrong one makes clean media look broken, so the analyser tries both and keeps whichever explains the data. Separation is measured at the first percentile rather than at the single closest pulse, because a real capture always carries a few strays and one of them should not decide the verdict; the stray count is reported on its own.

A revolution is only whole when it spans one rotation, so a capture that stops part-way through leaves a trailing segment that is marked partial and kept out of the speed figures.

The readers have been run against real captures from public preservation dumps, a KryoFlux stream and a 16 MB SuperCard Pro image. Point `FDSTOOLKIT_FLUX_CORPUS` at a directory of your own and `pytest -m corpus` will check every capture in it: that it loads, that its speed is plausible and consistent across revolutions, that it fits a known pulse family, and that it separates cleanly.

### Tuning the drive

| Command | Output |
|---|---|
| `fdstoolkit tune CAPTURE` | What to adjust, coarse actions first, then the fine ones |
| `fdstoolkit tune-sweep CAPTURES...` | The speed window that reads clean, and the centre to settle on |
| `fdstoolkit reading CYCLES` | What a console tool's cycles-between-bytes figure means, and which way to turn |
| `fdstoolkit classes CAPTURE` | Judges a capture of pulse classes on what it can answer |

A disk-lister tool running on the console reports the average CPU cycles between bytes, and that figure converts exactly: the 2A03 runs at 1.7897725 MHz and a byte is eight bits, so 148 cycles is 96.74 kbit/s and 152 is 94.20. More cycles between bytes means a slower disk. This is the one path to a speed measurement that needs no capture hardware at all.

```console
$ fdstoolkit reading 152
94.20 kbit/s, cell 10616 ns (63.7 counts), -2.28% of nominal, in spec, run faster
turn the motor trimmer counter-clockwise to run faster
```

An FDSStick rounds every pulse to one of three lengths inside the device, so its captures carry no timing and cannot measure speed. What they can answer is how the three lengths are distributed and how many pulses fell outside all three, which `classes` reports.

The drive is measured against the bit rate, not against a rotation speed. The RAM adapter expects 96.4 kbit/s and tolerates ten percent either side, which is the only figure the hardware actually enforces; published rotation speeds for this mechanism disagree with each other by a factor of two, so the toolkit does not use them.

`tune` reports in two stages. Coarse names anything outside the band the adapter accepts, which the disk will refuse to read. Fine names what is inside the band and still off centre, because a drive that merely passes is not a drive that is set up. A settled drive reports that nothing is left to adjust.

```console
$ fdstoolkit tune capture.raw
96.40 kbit/s, cell 10373 ns (62.2 counts), +0.00% of nominal, fine, hold
steady, wow and flutter 0.00%, drift +0.00%, spread 0.00%
score 100%
settled, nothing left to adjust
```

```console
$ fdstoolkit tune slow.raw
81.79 kbit/s, cell 12226 ns (73.4 counts), -15.15% of nominal, out of spec, run faster
periodic, wow and flutter 3.42%, drift +0.26%, spread 9.69%
score 6%
  [coarse] motor speed: -15.15% of nominal, outside the band the adapter tolerates.
           turn the motor trimmer counter-clockwise to run faster, then measure again
  [coarse] belt and spindle: wow and flutter 3.42%, spread 9.69%.
           replace or reseat the belt and check the spindle runs true, then measure again
```

Speed on its own does not separate a stretched belt from a misadjusted trimmer. The cell length is tracked across the capture, so a drive that wanders is named periodic, one that walks in one direction is named drifting, and only one that holds is called steady.

`tune-sweep` takes one capture per trimmer position and finds the range that reads clean. Set the trimmer to the centre of that range rather than to the first setting that works, because the width of the window is itself the measurement: a healthy drive reads over a wide span of speeds, a tired one only at a single point.

Tuning needs pulse timing, so a capture of pulse classes is refused rather than measured. A device that has already rounded every pulse to one of three nominal lengths has thrown away the thing being measured, and a speed derived from it would describe the rounding rather than the drive.

Speed and wobble say whether the drive is set up. They do not say whether a failed read was the drive or the disk, and that needs more than one disk. A failure at the same place on every disk is the drive; a failure on one disk alone is that disk. A drive that stops answering is neither, and the right response is to stop rather than to feed it another disk.

### Building masters

| Command | Output |
|---|---|
| `fdstoolkit masters DIR` | One master per game, by agreement across every dump in a directory |
| `fdstoolkit splice IMAGE --donor D -o OUT` | A bad block repaired from another dump of the same disk |
| `fdstoolkit reference-build DIR -o SET --set-version V` | A reference digest set others can check a dump against |
| `fdstoolkit reference-verify IMAGE --set SET` | Whether an image matches the reference for its game |
| `fdstoolkit dat-build DIR -o OUT --name N --set-version V` | A DAT for the tools the community already uses |

### Watching a disk over time

| Command | Output |
|---|---|
| `fdstoolkit archive-add IMAGE` | Records a dump against the physical disk it came from |
| `fdstoolkit archive-trend` | Whether a disk is holding, degrading or reading better, and how fast |

A disk is identified by what a kiosk stamped into it, so two copies of the same game are tracked apart. `--db` chooses where the record lives.

### Identifying

| Command | Output |
|---|---|
| `fdstoolkit identify IMAGE --dat FILE` | The matching DAT entry and which digest matched |
| `fdstoolkit identify IMAGE --dat FILE --reference DIR` | On no match, the nearest image in DIR and the differing byte runs |
| `fdstoolkit dat-cache` | The parsed-DAT cache. `--clear` empties it |
| `fdstoolkit bios FILE` | The BIOS revision, and which emulators accept the file. `--extract` pulls the 8 KB out of a larger dump |
| `fdstoolkit lint IMAGE` | Whether FDSKey will load the image |

### Hardware

| Command | Output |
|---|---|
| `fdstoolkit dump -o OUT` | Reads a disk. `--passes`, `--retries`, `--raw DIR` to keep pulse captures |
| `fdstoolkit write IMAGE` | Writes a disk, reads it back and compares. `--backup` first |
| `fdstoolkit consensus A B ... -o OUT` | Merges dumps by majority. `--map` prints per-block agreement |
| `fdstoolkit surface` | Writes and reads back four patterns to grade the media |

Both take `--backend simulation` or `--backend fdsstick`. The simulated backend takes `--source IMAGE` to stand in for the disk.

## Preserving a disk

Dump twice and compare, because one dump only says what the drive read once:

```bash
fdstoolkit dump -o pass1.fds --backend fdsstick --retries 3
fdstoolkit dump -o pass2.fds --backend fdsstick --retries 3
fdstoolkit diff pass1.fds pass2.fds
```

If the passes disagree, merge them instead of choosing one. Blocks are decided by majority and ties are reported:

```bash
fdstoolkit consensus pass1.fds pass2.fds pass3.fds -o merged.fds --map
```

Check the result, then identify it:

```bash
fdstoolkit verify merged.fds --strict
fdstoolkit identify merged.fds --dat "Nintendo - Family Computer Disk System.dat"
fdstoolkit hash merged.fds
```

The verify report calls out three things worth reading: hidden files, which are blocks past the declared count and are often real content; leftover data after the last block, which is what the disk held before it was last written; and checksum failures.

Write a working copy rather than playing the original:

```bash
fdstoolkit lint copy.fds
fdstoolkit write copy.fds --backend fdsstick --backup before.fds
```

Keep the original image as dumped, with hidden files, leftover data and bad checksums intact. Canonical and cleaned copies are derived from it, and each one reverses back with its sidecar.

## Measuring a disk

A checksum answers one bit about a 65,500-byte side: it matched or it did not. Three things say more.

**Repeated reads.** Dump the same disk several times and compare. Blocks that move are the disk or the drive failing, and the direction of the bit flips tells you which: magnetic decay loses transitions, so ones fall to zeros.

```console
$ fdstoolkit reads pass1.fds pass2.fds pass3.fds
passes        3
stability     99.88%
decay         loss
bits lost     14
bits gained   0
```

**The drive first.** A drive with a stretched belt misreads good disks. Measure it against a disk you trust before grading anything else.

```console
$ fdstoolkit calibrate known-good.fds --read r1.fds --read r2.fds
error rate    0.0000%
verdict       good
```

**Flux, when you have it.** Below the checksum is the layer where disk health actually lives: how tightly the pulse intervals cluster, and how close the closest one comes to the decision boundary. A disk at 90% margin is far from failing. One at 10% is about to.

```console
$ fdstoolkit flux capture.scp
track 0       27429 pulses, bit cell 10400 ns (96154 Hz)
  class 0     centre    10400 ns  jitter    412 ns  9143 pulses
  class 1     centre    15600 ns  jitter    398 ns  9143 pulses
  class 2     centre    20800 ns  jitter    405 ns  9143 pulses
  0 to 1      margin 68.4% at boundary 13000 ns
  speed       96.02 rpm
worst margin  68.4% on track 0
verdict       healthy
```

The thresholds are fitted to the capture rather than assumed, so a disk read at a different speed still decodes and the measured bit rate is reported rather than taken on faith.

A grade then carries the measurement that produced it:

```console
$ fdstoolkit grade disk.fds --read pass2.fds --margin 0.68
clean, confidence 0.97
  ok   errors 0 within 0
  ok   confidence 0.97 within 0.6
  ok   read stability 1 within 1
```

## Masters

No Nintendo master image exists. Disks were sold blank and written at a kiosk, and the kiosk stamped each one with its own serial, the date and a rewrite count, so two copies of the same game differ in bytes. The closest thing to a master is what every surviving dump agrees on once that stamp is set aside.

```console
$ fdstoolkit masters ~/dumps
profile       release
dumps         2597
games         1142
unanimous     1139 of 1142
```

Publish the result so anyone can check a dump without installing anything:

```console
$ fdstoolkit reference-build ~/dumps -o fds-reference.json --set-version 2026-09-22
$ fdstoolkit reference-verify mine.fds --set fds-reference.json
verdict       match
```

When one dump has a block no other dump has trouble with, take it:

```console
$ fdstoolkit splice broken.qd --donor other.qd -o repaired.fds
side 0 block  47  file_data    taken from other.qd
```

## Watching a disk age

Nothing in the ecosystem records how a disk changes. Dump it now, dump it again next year, and the archive answers whether it is worth re-dumping ahead of the others.

```console
$ fdstoolkit archive-add disk.fds --drive AN-500B
$ fdstoolkit archive-trend
4f2a...c19b: degrading, +10.0 blocks a year, unreadable in about 8 years
```

## Identity

Two dumps of one game are rarely byte-identical, because a kiosk rewrite changes the manufacturing date, the rewritten date, the Disk Writer serial and the rewrite count. Across 1,513 sides measured here, 352 groups hold identical file data and still differ in those fields.

`fdstoolkit canon` and `fdstoolkit hash` therefore report identity at four levels, and every digest carries the level that produced it:

| Profile | Question it answers |
|---|---|
| `raw` | Is this the same dump of the same physical disk |
| `content` | Is this the same software, whatever disk it came from |
| `release` | Is this the same release, from a factory disk or a rebuild |
| `data` | Is the program identical, ignoring the disk label |

A disk created with `fdstoolkit blank --formatted` or `fdstoolkit build` carries the values a factory disk carries, measured from 1,729 never-rewritten sides: country `0x49`, the constants at `$23` and `$25`, and `0xFF` in the kiosk fields that a Disk Writer would fill in. No date comes from the clock, so two runs produce identical bytes.

`release` also masks the country code, since the platform was Japan-only and the field names no release. It is masked rather than filled in: 409 sides carry a zero country byte next to a blank provenance region, and 22 carry a dumper's signature written over it.

Canonicalisation is reversible. `fdstoolkit canon -o` writes the canonical image and a sidecar holding everything the profile masked.

## Formats

A side is a sequence of blocks:

| Block | Code | Length | Contents |
|---|---|---|---|
| Disk information | `0x01` | 56 | Verification string, game code, dates, kiosk provenance |
| File amount | `0x02` | 2 | How many files the disk declares |
| File header | `0x03` | 16 | Number, id, name, load address, size, kind |
| File data | `0x04` | 1 + size | The file |

| Container | Side size | Checksums | Notes |
|---|---|---|---|
| `.fds` headerless | 65500 | No | What No-Intro hashes |
| `.fds` with fwNES header | 16 + 65500 per side | No | The header carries the side count |
| `.qd` | 65536 | Yes | Virtual Console rips and Quick Disk dumps |
| FDSKey card file | 65500 | No | Headerless `.fds` within the firmware limits |
| Copier per-side files | One file per side, lettered from A | Depends | A side may exceed the nominal length |
| ares side files | 73728 | Yes | Gaps and sync marks included |
| Raw pulse stream | Variable | Yes | What the drive reads |
| SuperCard Pro `.scp` | Variable | Yes | Flux intervals, 25 ns resolution |
| KryoFlux stream | Variable | Yes | Flux intervals, index blocks split revolutions |
| HxC `.hfe` | Variable | Yes | Bitcells rather than intervals |

What each conversion costs:

| From | To | What is lost |
|---|---|---|
| `.fds` headered | `.fds` headerless | The declared side count |
| `.fds` | `.qd` | Nothing. The checksums are computed from the data |
| `.qd` | `.fds` | Every checksum, so verify before converting |
| `.qd` with null checksums | `.fds` then `.qd` | The null checksums, unless `--crc-mode null` |
| Either | per-side files | The side ordering, which the file suffixes carry |
| Either | pulse stream | The original gap lengths, regenerated to specification |
| Any image | `content` or `release` | The provenance fields, recoverable from the sidecar |

A `.qd` from another system is refused by name rather than misread. HxC flux images and Sharp MZ disks in QDF and MZQ form each carry their own signature.

### Multi-disk games

A disk has two sides, so a `.fds` of 131,000 bytes holds one physical disk. A two-disk game arrives either as two files or as one file of four sides, which collections label `[Merged]`.

```bash
fdstoolkit merge "Game (Disk 1).fds" "Game (Disk 2).fds" -o "Game [Merged].fds"
fdstoolkit unmerge "Game [Merged].fds" -d ./disks
```

The split reads the boundary from the disk information rather than the file size, since a set may label its disks with different game codes while leaving the disk number at zero.

### Load times

There is no fragmentation on a Famicom disk. A side is one sequential stream with no allocation table, so a file cannot be split across non-adjacent regions.

What costs time is distance from the start of the side. `fdstoolkit layout` reports each file's offset in bytes and in seconds, plus dead weight after the last block, which `fdstoolkit rebuild` removes.

### Booting

`fdstoolkit boot` reports what a console does with a side. The BIOS loads every file whose ID is at or below the boot code, then compares 224 bytes of PPU memory at `$2800` against its copy of the licence screen and stops with error 20 if they differ.

The approval data is matched by what the file loads rather than by its name, since *Super Mario Bros.* carries it in a nametable file with an unreadable name. A side without one is reported as needing the NMI bypass rather than as failing, because unlicensed titles and second disks of a set both produce that result.

## Emulators and flash carts

`fdstoolkit export --target` writes the layout a device expects and, with `--bios`, places the BIOS where that device looks for it:

| Target | Layout | BIOS path |
|---|---|---|
| `nt-mini` | Headerless, a whole number of 65500-byte sides | `BIOS/fds.bin` |
| `mister` | `.fds` | `boot0.rom` |
| `everdrive-n8-pro` | `.fds` | `EDN8/syscore/disksys.rom` |
| `mesen2` | `.fds` | `disksys.rom` |
| `fceux` | `.fds` | `disksys.rom`, exactly 8192 bytes |
| `ares` | One 73728-byte file per side | Not used |

An export warns when the title appears on the device's list of games that do not work with automatic side swapping.

`fdstoolkit bios` recognises the three BIOS revisions MAME lists and four official re-release variants, extracts the 8 KB from a 40 KB or iNES-wrapped dump, and reports which emulators accept the file.

Saves are read and written as IPS (Mesen2, puNES), UPS (Nestopia UE), BPS, or as a whole image (FCEUX, Nt Mini). A headerless save merges into a headered image and the other way round.

## Hardware

| Device | Support |
|---|---|
| FDSStick with an adapter cable | Dump and write |
| Famicom Dumper over USB | Protocol implemented and tested; the CLI does not open the serial link yet, so it is driven from the library |
| FDSKey | The PC prepares and checks the SD card |

A write takes a verified backup, asks before overwriting, retries per block, then reads the whole disk back and compares. The final grade is clean, marginal when blocks needed retries, unstable when reads disagree, or failed.

Before writing:

- The drive needs its own power supply. The USB device cannot run it.
- A drive with an FD3206 controller refuses a full-surface write and cannot report the refusal. The read-back comparison is the only way to detect it, and a disk that comes back unchanged is reported as that case.
- A drive with misaligned heads writes disks only it can read, so a clean read-back does not prove the disk works elsewhere.

`fdstoolkit dump --raw DIR` keeps the pulse captures alongside the decoded image.

## No game data

This repository contains no disk image, no BIOS and no link to either. The tests generate their own disks.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports go through [SECURITY.md](SECURITY.md).

## Licence

MIT. See [LICENSE](LICENSE).
