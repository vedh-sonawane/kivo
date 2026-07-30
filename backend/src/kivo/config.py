"""Backend configuration.

Deliberately tiny: a frozen dataclass populated from environment variables with
sane defaults. No settings framework — there is not yet enough configuration to
justify one, and this keeps dependencies minimal.

Defaults are imported from the components that own them (the serial transport
owns the baud rate; the device client owns the timeouts) so a value is defined
in exactly one place.

Environment variables:

* ``KIVO_SERIAL_PORT``      e.g. ``COM3`` (Windows) or ``/dev/ttyACM0`` (Linux)
* ``KIVO_BAUD``             default 115200
* ``KIVO_RESPONSE_TIMEOUT`` seconds to wait for a response, default 2.0
* ``KIVO_READY_TIMEOUT``    seconds to wait for the boot READY, default 5.0
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .device.client import DEFAULT_READY_TIMEOUT, DEFAULT_RESPONSE_TIMEOUT
from .transport.serial_transport import DEFAULT_BAUD


@dataclass(frozen=True, slots=True)
class Settings:
    serial_port: str | None = None
    baud: int = DEFAULT_BAUD
    response_timeout: float = DEFAULT_RESPONSE_TIMEOUT
    ready_timeout: float = DEFAULT_READY_TIMEOUT

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            serial_port=os.environ.get("KIVO_SERIAL_PORT"),
            baud=int(os.environ.get("KIVO_BAUD", DEFAULT_BAUD)),
            response_timeout=float(
                os.environ.get("KIVO_RESPONSE_TIMEOUT", DEFAULT_RESPONSE_TIMEOUT)
            ),
            ready_timeout=float(
                os.environ.get("KIVO_READY_TIMEOUT", DEFAULT_READY_TIMEOUT)
            ),
        )
