from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Final, Protocol, runtime_checkable

from fdstoolkit.hardware.ports import BlockRead, DriveStatus, FaultKind, HardwareFaultError

MIN_PROTOCOL_VERSION: Final = 3
CRC_FLAG_SIZE: Final = 2


class Command(IntEnum):
    FDS_READ_REQUEST = 45
    READ_RESULT_BLOCK = 46
    READ_RESULT_END = 47
    TIMEOUT = 48
    NOT_CONNECTED = 49
    BATTERY_LOW = 50
    DISK_NOT_INSERTED = 51
    END_OF_HEAD = 52
    WRITE_REQUEST = 53
    WRITE_DONE = 54
    DISK_WRITE_PROTECTED = 57
    BLOCK_CRC_ERROR = 58


@dataclass(frozen=True, slots=True)
class Packet:
    command: Command
    payload: bytes


FAULTS: Final[dict[Command, tuple[str, FaultKind]]] = {
    Command.TIMEOUT: ("the dumper timed out waiting for the drive", FaultKind.TIMEOUT),
    Command.NOT_CONNECTED: ("the RAM adapter is not connected", FaultKind.LINK),
    Command.BATTERY_LOW: ("the battery is too low to drive the disk", FaultKind.MEDIA),
    Command.DISK_NOT_INSERTED: ("no disk is in the drive", FaultKind.MEDIA),
    Command.BLOCK_CRC_ERROR: ("a block failed its CRC on the dumper", FaultKind.MEDIA),
    Command.DISK_WRITE_PROTECTED: ("the disk is write protected", FaultKind.PROTECTED),
}


@runtime_checkable
class DumperLink(Protocol):
    def protocol_version(self) -> int: ...

    def send(self, packet: Packet) -> None: ...

    def receive(self) -> Packet: ...

    def close(self) -> None: ...


class FamicomDumper:
    reports_write_protection: Final = True
    selects_sides: Final = False

    def __init__(self, link: DumperLink) -> None:
        version = link.protocol_version()
        if version < MIN_PROTOCOL_VERSION:
            message = (
                f"this dumper speaks protocol version {version}, "
                f"and {MIN_PROTOCOL_VERSION} is the minimum that carries the FDS commands"
            )
            raise HardwareFaultError(message, kind=FaultKind.LINK)

        self._link = link
        self._disk_present = True
        self._write_protected = False
        self._battery_ok = True

    def close(self) -> None:
        self._link.close()

    def status(self) -> DriveStatus:
        return DriveStatus(
            disk_present=self._disk_present,
            write_protected=self._write_protected,
            battery_ok=self._battery_ok,
            ready=True,
        )

    def _record(self, command: Command) -> None:
        if command is Command.DISK_NOT_INSERTED:
            self._disk_present = False
        elif command is Command.DISK_WRITE_PROTECTED:
            self._write_protected = True
        elif command is Command.BATTERY_LOW:
            self._battery_ok = False

    def _raise_for(self, command: Command) -> None:
        fault = FAULTS.get(command)
        if fault is None:
            return
        self._record(command)
        message, kind = fault
        raise HardwareFaultError(message, kind=kind)

    def read_side(self, side: int) -> Iterator[BlockRead]:
        self._link.send(Packet(command=Command.FDS_READ_REQUEST, payload=bytes([side])))

        index = 0
        while True:
            packet = self._link.receive()
            self._raise_for(packet.command)

            if packet.command is Command.READ_RESULT_END:
                return
            if packet.command is not Command.READ_RESULT_BLOCK:
                message = f"the dumper answered with an unexpected command {packet.command}"
                raise HardwareFaultError(message, kind=FaultKind.LINK)

            body = packet.payload[:-CRC_FLAG_SIZE]
            crc_ok = bool(packet.payload[-CRC_FLAG_SIZE])
            end_of_head = bool(packet.payload[-1])

            yield BlockRead(index=index, payload=body, crc_ok=crc_ok, attempts=1)
            index += 1

            if end_of_head:
                return

    def write_side(self, side: int, blocks: Sequence[bytes]) -> None:
        for number, payload in enumerate(blocks):
            self._link.send(
                Packet(
                    command=Command.WRITE_REQUEST,
                    payload=bytes([side, number]) + len(payload).to_bytes(2, "little") + payload,
                )
            )

        packet = self._link.receive()
        self._raise_for(packet.command)
        if packet.command is not Command.WRITE_DONE:
            message = f"the dumper did not confirm the write, it answered {packet.command}"
            raise HardwareFaultError(message, kind=FaultKind.LINK)
