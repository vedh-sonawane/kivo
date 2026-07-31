"""Per-sensor calibration — so Kivo learns *your* sensor instead of guessing.

A photoresistor's raw numbers depend on the exact part, the divider resistor,
the wiring, and the room. Hardcoded absolute thresholds therefore can't be right
for everyone. Instead we measure the sensor's real bright and dark readings once
(``kivo calibrate light``) and derive thresholds from them, persisted to a small
JSON file. ``kivo run`` loads them. No magic numbers baked into logic.

File location: ``$KIVO_CALIBRATION_PATH`` if set, else ``~/.kivo/calibration.json``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

# Fractions of the observed bright..dark span at which the band boundaries sit.
_DARK_FRACTION = 0.33
_BRIGHT_FRACTION = 0.66


@dataclass(frozen=True, slots=True)
class LightThresholds:
    dark_below: int
    bright_above: int


def compute_thresholds(
    bright: int, dark: int, *, dark_fraction: float = _DARK_FRACTION,
    bright_fraction: float = _BRIGHT_FRACTION,
) -> LightThresholds:
    """Derive band thresholds from measured bright/dark readings.

    Raises ``ValueError`` if ``bright`` is not clearly greater than ``dark``
    (which would mean the sensor is miswired or unresponsive).
    """
    if bright <= dark:
        raise ValueError(
            f"bright reading ({bright}) must exceed dark reading ({dark}); "
            "check the sensor wiring/orientation"
        )
    span = bright - dark
    return LightThresholds(
        dark_below=round(dark + span * dark_fraction),
        bright_above=round(dark + span * bright_fraction),
    )


def calibration_path() -> Path:
    override = os.environ.get("KIVO_CALIBRATION_PATH")
    return Path(override) if override else Path.home() / ".kivo" / "calibration.json"


def _load_all() -> dict:
    path = calibration_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def load_thresholds(sensor: str) -> LightThresholds | None:
    """Load saved thresholds for ``sensor``, or ``None`` if not calibrated."""
    entry = _load_all().get(sensor)
    if not isinstance(entry, dict):
        return None
    try:
        return LightThresholds(
            dark_below=int(entry["dark_below"]),
            bright_above=int(entry["bright_above"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def save_thresholds(sensor: str, thresholds: LightThresholds) -> None:
    """Persist thresholds for ``sensor`` (merging with any other sensors)."""
    path = calibration_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    everything = _load_all()
    everything[sensor] = {
        "dark_below": thresholds.dark_below,
        "bright_above": thresholds.bright_above,
    }
    path.write_text(json.dumps(everything, indent=2), encoding="utf-8")
