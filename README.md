<div align="center">

<h1>fdstoolkit</h1>

<strong>Read, verify and identify Famicom Disk System images, and dump or write real disks.</strong>

[![ci](https://github.com/gufranco/fdstoolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/gufranco/fdstoolkit/actions/workflows/ci.yml)
[![analysis](https://github.com/gufranco/fdstoolkit/actions/workflows/analysis.yml/badge.svg)](https://github.com/gufranco/fdstoolkit/actions/workflows/analysis.yml)
[![coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)](#development)
[![tests](https://img.shields.io/badge/tests-898-brightgreen)](#development)
[![types](https://img.shields.io/badge/types-pyright%20strict-blue)](#development)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

<p align="center">
  <a href="#quick-start"><strong>Quick start</strong></a> &nbsp;|&nbsp;
  <a href="#commands">Commands</a> &nbsp;|&nbsp;
  <a href="#identity">Identity</a> &nbsp;|&nbsp;
  <a href="#hardware"><strong>Hardware</strong></a>
</p>

</div>

**38** commands · **898** tests · **100%** coverage · **1,042** images measured · **no** disk image, BIOS or link to either

---

## The problem

The tools in circulation answer the easy half of the question. They convert a good image into another good image. They do not tell you whether a dump is trustworthy, what a conversion threw away, why two dumps of the same game differ, what a console would do with the disk, or whether the disk you just overwrote was written correctly.

```console
$ fdstoolkit info "Falsion (Japan).fds"
Falsion (Japan).fds: fds container, 2 side(s), 131000 bytes
  side 0: FAL files=6 hidden=0 rewrites=0
  side 1: FAL files=10 hidden=0 rewrites=0

$ fdstoolkit diff "Falsion (Japan).fds" "Falsion (Japan).qd" --explain
same software, 6 provenance field(s) differ
  side 0 manufacturing_date (provenance): 1987-10-09 against 1987-09-22
  side 0 unknown_27 (provenance): 0099032001 against 00ffffff00
  side 0 rewritten_date (provenance): 1987-10-09 against ffffff

$ fdstoolkit canon "Falsion (Japan).qd" --profile release
fdstoolkit:v1:release/v1:826f23fad684f7acdb59b0132c4714e080f80e7a63e19cbce8a964e384fc1186
```

Those are dumps of two different physical disks, in two different containers, and the last line is the same for both.

## What it does

| Area | Capability |
|---|---|
| Convert | `.fds` headered or headerless, `.qd`, raw pulse streams, per-side copier files, ares side files |
| Verify | Checksum per block, structure, hidden files, leftover data, and the error a console would show |
| Identify | Match against a No-Intro DAT on any digest it carries, or report the nearest known image when nothing matches |
| Determinism | Four identity levels, so the same release compares equal whatever disk it came from |
| Create | Blank disks, or a whole disk built from a JSON manifest |
| Edit | List, extract, insert and remove files, hidden ones included |
| Repair | Rebuild an image from its parsed model: checksums, declared sizes, leftover data |
| Patch | IPS, UPS and BPS, applied correctly whether the patch assumed a header or not |
| Saves | Merge or extract emulator saves, and find which file is the save by comparing dumps |
| Export | The layout each device expects, with the BIOS placed where it looks for it |
| BIOS | Identify a disk system BIOS, extract one from a larger dump, and say which emulators accept it |
| Hardware | Dump and write real disks through an FDSStick, with retries, stability passes and read-back verification |

## Quick start

### Install

```bash
brew tap gufranco/fdstoolkit https://github.com/gufranco/fdstoolkit
brew install gufranco/fdstoolkit/fdstoolkit
```

Or straight from the repository, with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/gufranco/fdstoolkit
```

This is not on PyPI, deliberately. The two lines above are the whole distribution.

### Verify

```bash
fdstoolkit doctor
```

### Use it

```bash
fdstoolkit info game.fds                      # what is on the disk
fdstoolkit verify game.fds --strict           # does it hold together
fdstoolkit hash game.fds                      # every digest, including the canonical one
fdstoolkit boot game.fds                      # what the console would do with it
fdstoolkit identify game.fds --dat fds.dat    # what it is
fdstoolkit convert game.fds -o game.qd        # convert, losslessly
fdstoolkit layout game.fds                    # where each file sits, and what it costs to reach
fdstoolkit rebuild game.fds -o fixed.fds      # repair what can be repaired
```

Every command takes `--json` where a report makes sense, with sorted keys and no timestamp, so the output is diffable and scriptable. The exit code follows the worst finding.

## Commands

`fdstoolkit --help` lists all of them, and `fdstoolkit <command> --help` explains one.

## Identity

**Two dumps of one game are not byte-identical, and neither is wrong.** Measured across 1,513 sides: 352 groups hold identical file data and still differ, always in the disk information block, in the fields a kiosk rewrites.

So identity comes at four levels, and every digest prints which one produced it:

| Level | Answers |
|---|---|
| `raw` | Is this the same dump of the same physical disk |
| `content` | Is this the same software, whatever disk it came from |
| `release` | Is this the same release, whether it came off a factory disk or was rebuilt |
| `data` | Is the program identical, ignoring the disk label |

Of 144 corpus groups whose file data is byte-identical, `content` agrees on 125 and `release` agrees on 142. The two that remain are one physical side labelled disk 0 in one dump and disk 1 in another, which is a real difference and stays visible.

**A save is not "the last file".** That rule fails on the measurements: the differing file sat at the end in 17 pairs and four or more files from the end in 25. So a save is identified from evidence, by comparing dumps, or from a declared recipe, and a suggestive filename is a hint that is reported and never acted on.

**Nothing written depends on when or where it ran.** Dates come from the manifest or from a fixed default, never from the clock. Reports carry no timestamp unless asked.

## Hardware

| Device | What it can do |
|---|---|
| FDSStick with an adapter cable | Dump and write real disks from the PC |
| Famicom Dumper over USB | The protocol is implemented and tested, including the status codes for a missing disk, a flat battery and a write-protected disk. The CLI does not open its serial link yet, so it is driven from the library |
| FDSKey | Emulates a drive, so the PC only prepares and checks the SD card |

The write path assumes the worst, because the hardware gives it no choice. The drive reports no error codes, and a write refused by an FD3206 controller is invisible to the host. So a write dumps and verifies a backup first, asks before overwriting, retries per block, then re-reads the whole disk and compares. A disk that reads back exactly as it was before is reported as what that controller does when it silently refuses a full-surface write.

## No game data

This repository holds no disk image, no BIOS, and no link to either. Tests run on synthetic disks the toolkit generates. A test that needs a real dump is skipped unless `FDSTOOLKIT_CORPUS` points at a directory of your own files.

## Development

```bash
uv sync --all-extras --dev
uv run pytest --cov
```

Gates: `ruff format --check`, `ruff check`, `pyright` strict, and the suite at 100% coverage, statements and branches. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT. See [LICENSE](LICENSE).
