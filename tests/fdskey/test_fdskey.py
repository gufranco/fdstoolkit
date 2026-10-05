from __future__ import annotations

import hashlib

from fdstoolkit.build.blank import blank_image
from fdstoolkit.build.fdskey import fdskey_check
from fdstoolkit.codecs.fds import decode
from fdstoolkit.core.blocks import Block, BlockKind, FileKind
from fdstoolkit.core.disk import Disk, Side
from fdstoolkit.edit.files import FileSpec, insert_file, set_declared_file_count

VERIFICATION = slice(1, 15)


def formatted(*, sides: int = 1) -> Disk:
    disk, _ = decode(blank_image(sides=sides, headered=False, formatted=True, game_name="SMB"))
    return disk


def with_files(disk: Disk, sizes: list[int], *, declared: int | None = None) -> Disk:
    for index, size in enumerate(sizes):
        data = hashlib.shake_256(f"file{index}".encode()).digest(size)
        spec = FileSpec(name=f"F{index}", address=0x6000, kind=FileKind.PROGRAM, data=data)
        disk = insert_file(disk, side=0, spec=spec)
    if declared is None:
        return disk
    return set_declared_file_count(disk, side=0, count=declared)


def replaced_side(disk: Disk, side: Side) -> Disk:
    return Disk(sides=(side, *disk.sides[1:]))


def test_an_ordinary_game_loads_whole() -> None:
    disk = with_files(formatted(sides=2), [64, 128])

    check = fdskey_check(disk)

    assert (check.refusals, check.drops) == ((), ())


def test_a_side_without_the_nintendo_string_is_refused() -> None:
    disk = with_files(formatted(), [64])
    info = bytearray(disk.sides[0].blocks[0].payload)
    info[VERIFICATION] = bytes(14)
    blocks = (Block(kind=BlockKind.DISK_INFO, payload=bytes(info)), *disk.sides[0].blocks[1:])
    side = Side(blocks=blocks, tail=b"", capacity=disk.sides[0].capacity)

    check = fdskey_check(replaced_side(disk, side))

    assert check.refusals == (
        "side 0: FDSKey refuses a side whose disk information lacks *NINTENDO-HVC*",
    )


def test_an_unformatted_side_is_refused() -> None:
    disk, _ = decode(blank_image(sides=1, headered=False, formatted=False, game_name="SMB"))

    check = fdskey_check(disk)

    assert check.refusals == (
        "side 0: FDSKey refuses a side whose disk information lacks *NINTENDO-HVC*",
    )


def test_declared_files_beyond_the_budget_are_refused() -> None:
    disk = with_files(formatted(), [30000, 33000])

    check = fdskey_check(disk)

    assert len(check.refusals) == 1
    assert check.refusals[0].startswith("side 0: FDSKey cannot hold the 2 declared files")


def test_a_hidden_file_beyond_the_budget_is_named_as_dropped() -> None:
    disk = with_files(formatted(), [60000, 4000], declared=1)

    check = fdskey_check(disk)

    assert check.refusals == ()
    assert check.drops == ("side 0: FDSKey has no room for hidden file 1, F1, and drops it",)


def test_bytes_after_the_last_block_are_named_as_dropped() -> None:
    disk = with_files(formatted(), [64])
    side = disk.sides[0]
    tailed = Side(blocks=side.blocks, tail=b"\x05\x6d\xb6\xdb", capacity=side.capacity)

    check = fdskey_check(replaced_side(disk, tailed))

    assert check.drops == ("side 0: FDSKey stops at the last file and drops the 4 bytes after it",)


def test_a_block_out_of_order_ends_what_fdskey_loads() -> None:
    disk = with_files(formatted(), [64, 64])
    side = disk.sides[0]
    reordered = (*side.blocks[:3], side.blocks[4], side.blocks[3], *side.blocks[5:])
    swapped = Side(blocks=reordered, tail=b"", capacity=side.capacity)

    check = fdskey_check(replaced_side(disk, swapped))

    assert check.refusals == (
        "side 0: FDSKey cannot hold the 2 declared files: block 3 is out of order",
    )


def test_a_hidden_block_out_of_order_is_named_as_dropped() -> None:
    disk = with_files(formatted(), [64, 64], declared=1)
    side = disk.sides[0]
    reordered = (*side.blocks[:4], side.blocks[5], side.blocks[4])
    swapped = Side(blocks=reordered, tail=b"", capacity=side.capacity)

    check = fdskey_check(replaced_side(disk, swapped))

    assert check.refusals == ()
    assert check.drops == (
        "side 0: block 4 is out of order, so FDSKey drops it and every block after it",
    )
