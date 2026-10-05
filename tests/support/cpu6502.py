from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

MEMORY_SIZE: Final = 0x10000
STACK_PAGE: Final = 0x0100
RETURN_SENTINEL: Final = 0xFFF0
IO_FIRST: Final = 0x4020
IO_LAST: Final = 0x403F
CARRY: Final = 0x01
ZERO: Final = 0x02
INTERRUPT: Final = 0x04
DECIMAL: Final = 0x08
BREAK: Final = 0x10
UNUSED: Final = 0x20
OVERFLOW: Final = 0x40
NEGATIVE: Final = 0x80

ReadHook = Callable[[int, int], int]

IMPLIED = "imp"
ACCUMULATOR = "acc"
IMMEDIATE = "imm"
ZERO_PAGE = "zp"
ZERO_PAGE_X = "zpx"
ABSOLUTE = "abs"
ABSOLUTE_X = "absx"
ABSOLUTE_Y = "absy"
INDIRECT_Y = "indy"
INDIRECT = "ind"
RELATIVE = "rel"

READ_OPS: Final = frozenset(
    {"lda", "ldx", "ldy", "adc", "sbc", "and", "ora", "eor", "cmp", "cpx", "cpy", "bit"}
)
SHIFTS: Final = frozenset({"asl", "lsr", "rol", "ror"})

OPCODES: Final[dict[int, tuple[str, str, int]]] = {
    0xA9: ("lda", IMMEDIATE, 2),
    0xA5: ("lda", ZERO_PAGE, 3),
    0xB5: ("lda", ZERO_PAGE_X, 4),
    0xAD: ("lda", ABSOLUTE, 4),
    0xBD: ("lda", ABSOLUTE_X, 4),
    0xB9: ("lda", ABSOLUTE_Y, 4),
    0xB1: ("lda", INDIRECT_Y, 5),
    0xA2: ("ldx", IMMEDIATE, 2),
    0xA6: ("ldx", ZERO_PAGE, 3),
    0xAE: ("ldx", ABSOLUTE, 4),
    0xA0: ("ldy", IMMEDIATE, 2),
    0xA4: ("ldy", ZERO_PAGE, 3),
    0xAC: ("ldy", ABSOLUTE, 4),
    0x85: ("sta", ZERO_PAGE, 3),
    0x95: ("sta", ZERO_PAGE_X, 4),
    0x8D: ("sta", ABSOLUTE, 4),
    0x9D: ("sta", ABSOLUTE_X, 5),
    0x99: ("sta", ABSOLUTE_Y, 5),
    0x86: ("stx", ZERO_PAGE, 3),
    0x8E: ("stx", ABSOLUTE, 4),
    0x84: ("sty", ZERO_PAGE, 3),
    0x8C: ("sty", ABSOLUTE, 4),
    0x69: ("adc", IMMEDIATE, 2),
    0x65: ("adc", ZERO_PAGE, 3),
    0x75: ("adc", ZERO_PAGE_X, 4),
    0xE9: ("sbc", IMMEDIATE, 2),
    0xE5: ("sbc", ZERO_PAGE, 3),
    0xF5: ("sbc", ZERO_PAGE_X, 4),
    0xFD: ("sbc", ABSOLUTE_X, 4),
    0x29: ("and", IMMEDIATE, 2),
    0x25: ("and", ZERO_PAGE, 3),
    0x09: ("ora", IMMEDIATE, 2),
    0x05: ("ora", ZERO_PAGE, 3),
    0x49: ("eor", IMMEDIATE, 2),
    0xC9: ("cmp", IMMEDIATE, 2),
    0xC5: ("cmp", ZERO_PAGE, 3),
    0xCD: ("cmp", ABSOLUTE, 4),
    0xE0: ("cpx", IMMEDIATE, 2),
    0xC0: ("cpy", IMMEDIATE, 2),
    0x24: ("bit", ZERO_PAGE, 3),
    0x2C: ("bit", ABSOLUTE, 4),
    0xE6: ("inc", ZERO_PAGE, 5),
    0xEE: ("inc", ABSOLUTE, 6),
    0xC6: ("dec", ZERO_PAGE, 5),
    0xCE: ("dec", ABSOLUTE, 6),
    0xE8: ("inx", IMPLIED, 2),
    0xC8: ("iny", IMPLIED, 2),
    0xCA: ("dex", IMPLIED, 2),
    0x88: ("dey", IMPLIED, 2),
    0x0A: ("asl", ACCUMULATOR, 2),
    0x06: ("asl", ZERO_PAGE, 5),
    0x4A: ("lsr", ACCUMULATOR, 2),
    0x46: ("lsr", ZERO_PAGE, 5),
    0x2A: ("rol", ACCUMULATOR, 2),
    0x26: ("rol", ZERO_PAGE, 5),
    0x6A: ("ror", ACCUMULATOR, 2),
    0x66: ("ror", ZERO_PAGE, 5),
    0x10: ("bpl", RELATIVE, 2),
    0x30: ("bmi", RELATIVE, 2),
    0x90: ("bcc", RELATIVE, 2),
    0xB0: ("bcs", RELATIVE, 2),
    0xD0: ("bne", RELATIVE, 2),
    0xF0: ("beq", RELATIVE, 2),
    0x4C: ("jmp", ABSOLUTE, 3),
    0x6C: ("jmp", INDIRECT, 5),
    0x20: ("jsr", ABSOLUTE, 6),
    0x60: ("rts", IMPLIED, 6),
    0x48: ("pha", IMPLIED, 3),
    0x68: ("pla", IMPLIED, 4),
    0x08: ("php", IMPLIED, 3),
    0x28: ("plp", IMPLIED, 4),
    0xAA: ("tax", IMPLIED, 2),
    0xA8: ("tay", IMPLIED, 2),
    0x8A: ("txa", IMPLIED, 2),
    0x98: ("tya", IMPLIED, 2),
    0xBA: ("tsx", IMPLIED, 2),
    0x9A: ("txs", IMPLIED, 2),
    0x18: ("clc", IMPLIED, 2),
    0x38: ("sec", IMPLIED, 2),
    0x58: ("cli", IMPLIED, 2),
    0x78: ("sei", IMPLIED, 2),
    0xD8: ("cld", IMPLIED, 2),
    0xEA: ("nop", IMPLIED, 2),
}

BRANCHES: Final[dict[str, tuple[int, bool]]] = {
    "bpl": (NEGATIVE, False),
    "bmi": (NEGATIVE, True),
    "bcc": (CARRY, False),
    "bcs": (CARRY, True),
    "bne": (ZERO, False),
    "beq": (ZERO, True),
}

FLAG_SETTERS: Final[dict[str, tuple[int, bool]]] = {
    "clc": (CARRY, False),
    "sec": (CARRY, True),
    "cli": (INTERRUPT, False),
    "sei": (INTERRUPT, True),
    "cld": (DECIMAL, False),
}


class UnsupportedOpcodeError(RuntimeError):
    pass


@dataclass
class Cpu:
    memory: bytearray = field(default_factory=lambda: bytearray(MEMORY_SIZE))
    a: int = 0
    x: int = 0
    y: int = 0
    sp: int = 0xFF
    pc: int = 0
    status: int = UNUSED | INTERRUPT
    cycles: int = 0
    read_hook: ReadHook | None = None

    def load(self, address: int, data: bytes) -> None:
        self.memory[address : address + len(data)] = data

    def read(self, address: int) -> int:
        if self.read_hook is not None and IO_FIRST <= address <= IO_LAST:
            return self.read_hook(address, self.cycles) & 0xFF
        return self.memory[address & 0xFFFF]

    def write(self, address: int, value: int) -> None:
        self.memory[address & 0xFFFF] = value & 0xFF

    def word(self, address: int) -> int:
        return self.memory[address & 0xFFFF] | self.memory[(address + 1) & 0xFFFF] << 8

    def call(self, address: int, *, limit: int = 50_000_000) -> None:
        self._push((RETURN_SENTINEL - 1) >> 8)
        self._push((RETURN_SENTINEL - 1) & 0xFF)
        self.pc = address
        start = self.cycles
        while self.pc != RETURN_SENTINEL:
            if self.cycles - start > limit:
                message = f"no return after {limit} cycles, at {self.pc:04X}"
                raise RuntimeError(message)
            self.step()

    def step(self) -> None:
        opcode = self.memory[self.pc]
        entry = OPCODES.get(opcode)
        if entry is None:
            message = f"opcode {opcode:02X} at {self.pc:04X}"
            raise UnsupportedOpcodeError(message)
        name, mode, base_cycles = entry
        self.pc += 1
        self.cycles += base_cycles
        if mode == RELATIVE:
            self._branch(name)
            return
        if mode in (IMPLIED, ACCUMULATOR):
            self._implied(name, mode)
            return
        address, crossed = self._address(mode)
        if crossed and name in READ_OPS:
            self.cycles += 1
        self._memory_op(name, address)

    def _push(self, value: int) -> None:
        self.memory[STACK_PAGE + self.sp] = value & 0xFF
        self.sp = (self.sp - 1) & 0xFF

    def _pull(self) -> int:
        self.sp = (self.sp + 1) & 0xFF
        return self.memory[STACK_PAGE + self.sp]

    def _flag(self, mask: int, *, on: bool) -> None:
        self.status = (self.status | mask) if on else (self.status & ~mask)

    def _nz(self, value: int) -> int:
        value &= 0xFF
        self._flag(ZERO, on=value == 0)
        self._flag(NEGATIVE, on=bool(value & NEGATIVE))
        return value

    def _address(self, mode: str) -> tuple[int, bool]:
        operand = self.pc
        if mode == IMMEDIATE:
            self.pc += 1
            return operand, False
        if mode in (ZERO_PAGE, ZERO_PAGE_X, INDIRECT_Y):
            self.pc += 1
            return self._zero_page_address(mode, self.memory[operand])
        self.pc += 2
        base = self.word(operand)
        if mode == INDIRECT:
            return self.word(base), False
        offset = {ABSOLUTE_X: self.x, ABSOLUTE_Y: self.y}.get(mode, 0)
        target = (base + offset) & 0xFFFF
        return target, (base & 0xFF00) != (target & 0xFF00)

    def _zero_page_address(self, mode: str, base: int) -> tuple[int, bool]:
        if mode == ZERO_PAGE:
            return base, False
        if mode == ZERO_PAGE_X:
            return (base + self.x) & 0xFF, False
        pointer = self.word(base)
        target = (pointer + self.y) & 0xFFFF
        return target, (pointer & 0xFF00) != (target & 0xFF00)

    def _branch(self, name: str) -> None:
        offset = self.memory[self.pc]
        self.pc += 1
        mask, wanted = BRANCHES[name]
        if bool(self.status & mask) != wanted:
            return
        target = (self.pc + (offset - 0x100 if offset & 0x80 else offset)) & 0xFFFF
        self.cycles += 1 + ((target & 0xFF00) != (self.pc & 0xFF00))
        self.pc = target

    def _shift(self, name: str, value: int) -> int:
        carry_in = self.status & CARRY
        if name in ("asl", "rol"):
            self._flag(CARRY, on=bool(value & 0x80))
            return self._nz((value << 1) | (carry_in if name == "rol" else 0))
        self._flag(CARRY, on=bool(value & 0x01))
        return self._nz((value >> 1) | ((carry_in << 7) if name == "ror" else 0))

    def _add(self, operand: int) -> None:
        total = self.a + operand + (self.status & CARRY)
        self._flag(CARRY, on=total > 0xFF)
        self._flag(OVERFLOW, on=bool(~(self.a ^ operand) & (self.a ^ total) & 0x80))
        self.a = self._nz(total)

    def _implied(self, name: str, mode: str) -> None:
        if mode == ACCUMULATOR:
            self.a = self._shift(name, self.a)
            return
        if name in FLAG_SETTERS:
            mask, on = FLAG_SETTERS[name]
            self._flag(mask, on=on)
            return
        handler = self._implied_handlers().get(name)
        if handler is not None:
            handler()

    def _implied_handlers(self) -> dict[str, Callable[[], None]]:
        return {
            "inx": lambda: setattr(self, "x", self._nz(self.x + 1)),
            "dex": lambda: setattr(self, "x", self._nz(self.x - 1)),
            "iny": lambda: setattr(self, "y", self._nz(self.y + 1)),
            "dey": lambda: setattr(self, "y", self._nz(self.y - 1)),
            "tax": lambda: setattr(self, "x", self._nz(self.a)),
            "tay": lambda: setattr(self, "y", self._nz(self.a)),
            "txa": lambda: setattr(self, "a", self._nz(self.x)),
            "tya": lambda: setattr(self, "a", self._nz(self.y)),
            "tsx": lambda: setattr(self, "x", self._nz(self.sp)),
            "txs": lambda: setattr(self, "sp", self.x),
            "pha": lambda: self._push(self.a),
            "pla": lambda: setattr(self, "a", self._nz(self._pull())),
            "php": lambda: self._push(self.status | BREAK | UNUSED),
            "plp": lambda: setattr(self, "status", (self._pull() & ~BREAK) | UNUSED),
            "rts": self._return,
        }

    def _return(self) -> None:
        low = self._pull()
        self.pc = ((self._pull() << 8) | low) + 1

    def _memory_op(self, name: str, address: int) -> None:
        if name in ("sta", "stx", "sty"):
            self.write(address, {"sta": self.a, "stx": self.x, "sty": self.y}[name])
        elif name == "jmp":
            self.pc = address
        elif name == "jsr":
            self._push((self.pc - 1) >> 8)
            self._push(self.pc - 1)
            self.pc = address
        elif name in ("inc", "dec"):
            self.write(address, self._nz(self.read(address) + (1 if name == "inc" else -1)))
        elif name in SHIFTS:
            self.write(address, self._shift(name, self.read(address)))
        else:
            self._read_op(name, self.read(address))

    def _read_op(self, name: str, operand: int) -> None:
        loads = {"lda": "a", "ldx": "x", "ldy": "y"}
        if name in loads:
            setattr(self, loads[name], self._nz(operand))
        elif name in ("adc", "sbc"):
            self._add(operand if name == "adc" else operand ^ 0xFF)
        elif name in ("and", "ora", "eor"):
            combined = {"and": self.a & operand, "ora": self.a | operand, "eor": self.a ^ operand}
            self.a = self._nz(combined[name])
        elif name in ("cmp", "cpx", "cpy"):
            register = {"cmp": self.a, "cpx": self.x, "cpy": self.y}[name]
            self._flag(CARRY, on=register >= operand)
            self._nz(register - operand)
        else:
            self._flag(ZERO, on=(self.a & operand) == 0)
            self._flag(NEGATIVE, on=bool(operand & NEGATIVE))
            self._flag(OVERFLOW, on=bool(operand & OVERFLOW))
