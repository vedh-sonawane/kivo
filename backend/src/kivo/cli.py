"""Command-line entry point for talking to a Kivo device.

Examples::

    kivo --fake ping                       # no hardware needed
    kivo --fake identify
    kivo --fake display "Hello Kivo"
    kivo --fake display "line 2" --row 1
    kivo --fake clear
    kivo --port COM3 ping                   # real ELEGOO Uno on COM3
    KIVO_SERIAL_PORT=COM3 kivo ping         # port via environment

Global options (``--port``, ``--baud``, ``--fake``, ``-v``) come before the
subcommand. This is the thinnest possible entry point: it wires up a transport
and a :class:`~kivo.device.client.DeviceClient`, then invokes one capability.
All real logic lives in the layers below.
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


# -- subcommand handlers: each takes (client, parsed args) and returns an exit code --


def _cmd_ping(client: DeviceClient, args: argparse.Namespace) -> int:
    client.ping()
    print("PONG - device is alive")
    return 0


def _cmd_identify(client: DeviceClient, args: argparse.Namespace) -> int:
    identity = client.identify()
    print(
        f"{identity.name} v{identity.version} "
        f"(Kivo Serial Protocol v{identity.protocol})"
    )
    return 0


def _cmd_display(client: DeviceClient, args: argparse.Namespace) -> int:
    client.display_write(args.text, row=args.row, col=args.col)
    print(f"wrote {args.text!r} at row {args.row}, col {args.col}")
    return 0


def _cmd_clear(client: DeviceClient, args: argparse.Namespace) -> int:
    client.display_clear()
    print("display cleared")
    return 0


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

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ping", help="check the device is alive").set_defaults(
        func=_cmd_ping
    )
    sub.add_parser("identify", help="print firmware name/version/protocol").set_defaults(
        func=_cmd_identify
    )

    display = sub.add_parser("display", help="write text to the LCD")
    display.add_argument("text", help="text to display")
    display.add_argument("--row", type=int, default=0, help="zero-based row (default 0)")
    display.add_argument("--col", type=int, default=0, help="zero-based column (default 0)")
    display.set_defaults(func=_cmd_display)

    sub.add_parser("clear", help="clear the LCD").set_defaults(func=_cmd_clear)

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
            return args.func(client, args)
    except (DeviceError, ProtocolError, TransportTimeout) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
