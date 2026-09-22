# Changelog

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [semantic versioning](https://semver.org/spec/v2.0.0.html).

## 0.1.0

First release. Everything below is new.

### Reading and writing images

Read and write headerless `.fds`, fwNES-headered `.fds`, `.qd` with its per-block checksums, MGD1 and Game Doctor per-side files, and the gapped pulse stream a drive actually produces. Every pair round-trips byte for byte over the 1,042-image corpus the toolkit was measured against, and any conversion that cannot express something reports it instead of writing a file that looks complete. The format reference under `docs/` states what each conversion loses.

Checksums are the reflected-0x8408 CRC-16 the hardware computes, confirmed against real `.qd` images rather than against a description of the algorithm.

### Verifying

`fds verify` reports every finding with a severity, and `--strict` fails on a warning too. `fds info` and `fds ls` answer what a side holds, hidden files included: a file past the declared count is usually the interesting part of a dump, so nothing here quietly normalises one away.

`fds rebuild` re-emits an image from its parsed model, recomputing a checksum that is null or wrong, correcting a file header whose declared size disagrees with its data, and dropping bytes after the last block. Hidden files survive unless `--drop-hidden` or `--reveal-hidden` says otherwise.

### Identity and determinism

Three identity levels, so a digest can never be read without knowing what produced it: `raw` for the exact bytes, `content` for the same software from any physical disk, `data` for the program alone. A canonical digest prints as `fdscanon:v1:<profile>/v1:<sha256>`, and canonicalisation is reversible through a sidecar that holds everything the projection removed.

The masking profile was derived from measurement, not assumption. Across 1,513 corpus sides, 484 groups share identical file data while 352 still differ as whole sides, and every one of those differences sits in a disk-information provenance field.

`fds identify` matches against a No-Intro style DAT, caches the parsed catalogue by content, and with `--reference` reports the nearest known image and the byte runs that separate it when nothing matches exactly. `fds diff --explain` answers with the field that moved rather than the block that differs.

### Creating and editing

Blank images from one to eight sides, formatted or not, headered or not, reproducing the reference hashes exactly. Disk building from a JSON manifest, including the licence string or none at all. File insertion and extraction, disk-information field edits, IPS, UPS and BPS patching, and save handling that finds the save area by comparing dumps rather than by guessing it is the last file, a rule the corpus disproves.

### Hardware

An FDSStick backend and a simulated drive that exercises the whole flow without a cable. The Famicom Dumper protocol is implemented and tested as a library, including the status codes for a missing disk, a flat battery and a write-protected disk; the CLI does not open its serial link yet. A dump can run several passes and merge them by per-block majority, with `fds consensus --map` printing where the passes disagreed. A write reads the disk back and compares, which is the only verification available: an FD3206 controller refuses a write without being able to say so.

Every hardware path is tested against a fake transport. None of it has touched a real drive. The hardware verification steps under `docs/` list what to run when the cable exists, and what a failure at each step would mean.

### FDSKey

Card images for both firmware variants, and `fds lint` predicting whether FDSKey will load an image before the card goes back in the machine.
