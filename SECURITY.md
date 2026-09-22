# Security

## Reporting

Report anything you believe is a security problem through
[GitHub's private vulnerability reporting](https://docs.github.com/code-security/security-advisories/guidance-on-reporting-and-writing/privately-reporting-a-security-vulnerability)
on this repository, rather than in a public issue. There is no service behind
this and no user data, so the realistic reports are about the supply chain and
about what a malformed input can make the code do.

## What is in scope

| Class | Example |
|-------|---------|
| Supply chain | A pinned action or a release artefact that has been tampered with |
| Malformed input | A crafted disk image, patch or DAT that makes the tool write outside its output folder, consume unbounded memory, or execute anything |
| Identification | An image that verifies against a DAT entry it is not, or a BIOS that identifies as a revision it is not |
| Hardware | Anything that makes the write path touch a disk without the confirmation and the backup it promises |
| Leakage | Any path where the tool would distribute, fetch, or point at a disk image or a BIOS |

The last two rows are security properties here rather than legal footnotes. A
write is irreversible on somebody's only copy of a thirty-year-old disk, and the
project's whole design is that it identifies files it must never carry.

## What is not

The tool reads files you already hold and writes files you asked for. It makes no
network request at all. A report that amounts to "this program can write a file"
is describing what it is for.

Emulator behaviour, drive behaviour and the correctness of third-party patches
are outside what this project can control.

## Where this is distributed

This repository's releases page and its Homebrew formula, and nowhere else.
Anything under this name from another source is not from this project.

## Supply chain

Every release carries a CycloneDX bill of materials and a Sigstore bundle over
it. The bill is generated from an environment holding nothing but this package
and its declared dependencies, and the release fails if anything else appears in
it.
