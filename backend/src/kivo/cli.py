"""Command-line entry point for talking to a Kivo device.

Examples::

    kivo --fake ping                 # no hardware needed
    kivo --fake identify
    kivo --port COM3 ping            # real ELEGOO Uno on COM3
    KIVO_SERIAL_PORT=COM3 kivo ping  # port via environment

This is the thinnest possible entry point: it wires up a transport and a
:class:`~kivo.device.client.DeviceClient`, then calls one capability. All real
logic lives in the layers below.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import Settings
from .device import DeviceClient
from .protocol.errors import DeviceError, ProtocolError, TransportTimeout
from .transport import FakeTransport, SerialTransport
from .transport.base import Transport


def _build_transport(args: argparse.Namespace, settings: Settings) -> Transport:
    if args.fake:
        return FakeTransport()
    port = args.port or settings.serial_port
    if not port:
        raise SystemExit(
            "no serial port: pass --port, set KIVO_SERIAL_PORT, or use --fake"
        )
    return SerialTransport(port, baud=args.baud or settings.baud)


def _cmd_ping(client: DeviceClient) -> int:
    client.ping()
    print("PONG - device is alive")
    return 0


def _cmd_identify(client: DeviceClient) -> int:
    identity = client.identify()
    print(
        f"{identity.name} v{identity.version} "
        f"(Kivo Serial Protocol v{identity.protocol})"
    )
    return 0


_COMMANDS = {
    "ping": _cmd_ping,
    "identify": _cmd_identify,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kivo", description="Talk to a Kivo device.")
    parser.add_argument("--port", help="serial port (e.g. COM3, /dev/ttyACM0)")
    parser.add_argument("--baud", type=int, help="baud rate (default 115200)")
    parser.add_argument(
        "--fake",
        action="store_true",
        help="use the in-memory device emulator instead of real hardware",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("command", choices=sorted(_COMMANDS), help="what to do")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    transport = _build_transport(args, settings)

    try:
        with DeviceClient(
            transport,
            response_timeout=settings.response_timeout,
            ready_timeout=settings.ready_timeout,
        ) as client:
            return _COMMANDS[args.command](client)
    except (DeviceError, ProtocolError, TransportTimeout) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
