from __future__ import annotations

from collections.abc import Mapping, Sequence

from fdstoolkit.hardware.fdsstick import PRODUCT_ID, VENDOR_ID


class FakeHandle:
    def __init__(self, error: OSError | None) -> None:
        self._error = error
        self.closed = False

    def open_path(self, path: bytes) -> None:
        del path
        if self._error is not None:
            raise self._error

    def close(self) -> None:
        self.closed = True


class FakeHid:
    def __init__(
        self,
        devices: Sequence[Mapping[str, object]],
        *,
        open_error: OSError | None = None,
    ) -> None:
        self._devices = [dict(device) for device in devices]
        self.handle = FakeHandle(open_error)
        self.listed = 0

    def device(self) -> FakeHandle:
        return self.handle

    def enumerate(self, vendor_id: int, product_id: int) -> list[dict[str, object]]:
        self.listed += 1
        return [
            device
            for device in self._devices
            if device["vendor_id"] == vendor_id and device["product_id"] == product_id
        ]


def stick(**extra: object) -> dict[str, object]:
    entry: dict[str, object] = {
        "vendor_id": VENDOR_ID,
        "product_id": PRODUCT_ID,
        "path": b"/dev/hidraw0",
    }
    return {**entry, **extra}
