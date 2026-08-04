# Kivo backend

The host-side "brain". A Python package, `kivo`, that talks to the device over
the Kivo Serial Protocol.

## Layout

```
backend/
  pyproject.toml
  src/kivo/
    config.py           settings from environment variables
    cli.py              `kivo` command-line entry point
    protocol/           codec: frames + CRC-8 (mirrors /protocol/README.md)
    transport/          Transport port + Serial and Fake adapters
    device/             DeviceClient - the capability API
  tests/                pytest suite (runs against the fake transport)
```

Dependencies point downward: `cli → device → protocol → transport`.

## Setup

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1      # Windows PowerShell
pip install -e ".[dev]"
```

## Use

```bash
kivo --fake ping                # emulated device, no hardware
kivo --fake identify
kivo --port COM3 ping           # real Uno on COM3
kivo -v --fake ping             # verbose: see the wire traffic
```

Configuration via environment variables: `KIVO_SERIAL_PORT`, `KIVO_BAUD`,
`KIVO_RESPONSE_TIMEOUT`.

## Test

```bash
pytest
```

The suite uses `FakeTransport`, an in-memory emulation of the firmware, so it
runs the entire protocol stack with no board attached.
