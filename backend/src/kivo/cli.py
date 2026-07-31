"""Command-line entry point for talking to a Kivo device.

Examples::

    kivo --fake ping                       # no hardware needed
    kivo --fake display "Hello Kivo"
    kivo --port COM3 ping                   # real ELEGOO Uno on COM3
    kivo --port COM3 run --ai               # autonomous companion mode
    KIVO_SERIAL_PORT=COM3 kivo ping         # port via environment

Global options (``--port``, ``--baud``, ``--fake``, ``-v``) come before the
subcommand. This is the thinnest possible entry point: it wires up a transport
and a :class:`DeviceClient`, then invokes one capability. Also holds the tiny
environment-driven :class:`Settings` (there isn't enough config to justify its
own module).
"""

from __future__ import annotations

import argparse
import logging
import os
import statistics
import sys
from dataclasses import dataclass

from .ai import (
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_TIMEOUT,
    AiNarrator,
    OllamaClient,
)
from .brain import (
    DEFAULT_SENSORS,
    Brain,
    LightMood,
    MoodEngine,
    PresenceGreeter,
    ProximityGreeter,
    TimeGreeter,
)
from .calibration import compute_thresholds, load_thresholds, save_thresholds
from .device import (
    DEFAULT_READY_TIMEOUT,
    DEFAULT_RESPONSE_TIMEOUT,
    DeviceClient,
)
from .protocol import DeviceError, ProtocolError, TransportError, TransportTimeout
from .transport import DEFAULT_BAUD, FakeTransport, SerialTransport, Transport


@dataclass(frozen=True, slots=True)
class Settings:
    """Backend configuration from environment variables, with sane defaults.

    ``KIVO_SERIAL_PORT``, ``KIVO_BAUD``, ``KIVO_RESPONSE_TIMEOUT``,
    ``KIVO_READY_TIMEOUT``, ``KIVO_OLLAMA_URL``, ``KIVO_OLLAMA_MODEL``,
    ``KIVO_AI_TIMEOUT``. Defaults come from the components that own them, so each
    value is defined in exactly one place.
    """

    serial_port: str | None = None
    baud: int = DEFAULT_BAUD
    response_timeout: float = DEFAULT_RESPONSE_TIMEOUT
    ready_timeout: float = DEFAULT_READY_TIMEOUT
    ollama_url: str = DEFAULT_OLLAMA_URL
    ollama_model: str = DEFAULT_MODEL
    ai_timeout: float = DEFAULT_TIMEOUT

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
            ollama_url=os.environ.get("KIVO_OLLAMA_URL", DEFAULT_OLLAMA_URL),
            ollama_model=os.environ.get("KIVO_OLLAMA_MODEL", DEFAULT_MODEL),
            ai_timeout=float(os.environ.get("KIVO_AI_TIMEOUT", DEFAULT_TIMEOUT)),
        )


def _build_transport(args: argparse.Namespace, settings: Settings) -> Transport:
    if args.fake:
        return FakeTransport()
    port = args.port or settings.serial_port
    if not port:
        raise SystemExit(
            "no serial port: pass --port, set KIVO_SERIAL_PORT, or use --fake"
        )
    return SerialTransport(port, baud=args.baud or settings.baud)


# -- subcommand handlers: each takes (client, parsed args) -> exit code --------


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


def _cmd_read(client: DeviceClient, args: argparse.Namespace) -> int:
    reading = client.sensor_read(args.sensor)
    print(f"{reading.name} = {reading.value}")
    return 0


def _cmd_watch(client: DeviceClient, args: argparse.Namespace) -> int:
    def on_event(event) -> None:
        reading = DeviceClient.parse_sensor_event(event)
        if reading is not None:
            print(f"{reading.name} = {reading.value}")
        else:
            print(f"[{event.name}] {event.data}".rstrip())

    client.set_event_handler(on_event)
    client.subscribe_sensor(args.sensor)
    print(f"watching '{args.sensor}' - press Ctrl+C to stop")
    try:
        client.listen()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def _median_read(client: DeviceClient, sensor: str, samples: int = 5) -> int:
    values = [client.sensor_read(sensor).value for _ in range(samples)]
    return int(statistics.median(values))


def _cmd_calibrate(client: DeviceClient, args: argparse.Namespace) -> int:
    sensor = args.sensor
    input(f"Make '{sensor}' BRIGHT (lights on / shine a light on it), then press Enter... ")
    bright = _median_read(client, sensor)
    print(f"  bright reading: {bright}")
    input(f"Now make '{sensor}' DARK (cover it / lights off), then press Enter... ")
    dark = _median_read(client, sensor)
    print(f"  dark reading:   {dark}")
    try:
        thresholds = compute_thresholds(bright, dark)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    save_thresholds(sensor, thresholds)
    print(
        f"calibrated '{sensor}': dark < {thresholds.dark_below}, "
        f"bright > {thresholds.bright_above}. Saved — 'kivo run' will use it now."
    )
    return 0


def _cmd_run(client: DeviceClient, args: argparse.Namespace) -> int:
    thresholds = load_thresholds("light")
    if thresholds is None:
        light = LightMood(row=1)
        print("tip: run 'kivo calibrate light' so Kivo learns your room's light range")
    else:
        light = LightMood(
            row=1,
            dark_below=thresholds.dark_below,
            bright_above=thresholds.bright_above,
        )

    if args.ai:
        settings = Settings.from_env()
        model = args.model or settings.ollama_model
        ai = OllamaClient(
            url=settings.ollama_url, model=model, timeout=settings.ai_timeout
        )
        # Top row = Kivo's AI voice (greeting, then fresh lines on light change,
        # arrival/leave, and lean-in); bottom row = the factual light level.
        if thresholds is None:
            ai_light = AiNarrator(ai, row=0)
        else:
            ai_light = AiNarrator(
                ai,
                row=0,
                dark_below=thresholds.dark_below,
                bright_above=thresholds.bright_above,
            )
        behaviors = [ai_light, light, MoodEngine()]
        print(f"Kivo is awake (AI: {model}) - press Ctrl+C to stop")
    else:
        # Row 0: wake greeting + arrival/leave + lean-in lines. Row 1: light.
        # MoodEngine drives the RGB LED + buzzer from the inferred mood.
        behaviors = [
            TimeGreeter(row=0),
            PresenceGreeter(row=0),
            ProximityGreeter(row=0),
            light,
            MoodEngine(),
        ]
        print("Kivo is awake - press Ctrl+C to stop")

    brain = Brain(client, behaviors, sensors=DEFAULT_SENSORS)
    try:
        brain.run()
    except KeyboardInterrupt:
        print("\nKivo is sleeping")
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

    read = sub.add_parser("read", help="read a sensor once")
    read.add_argument("sensor", help="sensor name (e.g. light)")
    read.set_defaults(func=_cmd_read)

    watch = sub.add_parser("watch", help="stream a sensor's values live")
    watch.add_argument("sensor", help="sensor name (e.g. light)")
    watch.set_defaults(func=_cmd_watch)

    calibrate = sub.add_parser(
        "calibrate", help="measure a sensor's real range so Kivo classifies it correctly"
    )
    calibrate.add_argument("sensor", help="sensor name (e.g. light)")
    calibrate.set_defaults(func=_cmd_calibrate)

    run = sub.add_parser("run", help="run Kivo as a live, autonomous companion")
    run.add_argument(
        "--ai",
        action="store_true",
        help="let a local AI (Ollama) speak as Kivo instead of fixed phrases",
    )
    run.add_argument(
        "--model",
        help="Ollama model for --ai (default: env KIVO_OLLAMA_MODEL or 'llama3'). "
        "A small model (e.g. llama3.2:3b) reacts much faster.",
    )
    run.set_defaults(func=_cmd_run)

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
    except (DeviceError, ProtocolError, TransportTimeout, TransportError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
