# Kivo

An AI-capable physical desk companion built around an **ELEGOO Uno R3**.

The Uno is the *hands* - it exposes hardware capabilities. The Python backend on
your PC is the *brain* - it holds all logic. The two talk over a small, robust,
checksummed serial protocol.

> This is a personal, long-lived project. It favors clarity, maintainability, and
> learning over both hobby-grade shortcuts and enterprise-grade over-engineering.

## Repository layout

| Path        | What it is                                                        |
|-------------|-------------------------------------------------------------------|
| `protocol/` | The wire-protocol spec — the source of truth for both sides.      |
| `firmware/` | PlatformIO project for the Uno (C++).                             |
| `backend/`  | Python package `kivo` — the host software (CLI now, API later).   |
| `docs/`     | Architecture overview and Architecture Decision Records (ADRs).   |

Start with [`docs/architecture.md`](docs/architecture.md) and
[`protocol/README.md`](protocol/README.md).

## Quick start (no hardware required)

The backend ships with an in-memory device emulator, so you can run the full
stack before wiring anything up.

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell:  .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest                        # run the test suite
kivo --fake identify          # talk to the emulated device
kivo --fake ping