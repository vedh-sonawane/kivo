"""Tests for per-sensor light calibration (threshold math + persistence)."""

import pytest

from kivo.calibration import (
    LightThresholds,
    compute_thresholds,
    load_thresholds,
    save_thresholds,
)


def test_compute_thresholds_orders_bands_within_range():
    t = compute_thresholds(bright=900, dark=100)  # span 800
    assert t.dark_below == round(100 + 800 * 0.33)
    assert t.bright_above == round(100 + 800 * 0.66)
    assert 100 < t.dark_below < t.bright_above < 900


def test_compute_thresholds_rejects_bright_not_above_dark():
    with pytest.raises(ValueError):
        compute_thresholds(bright=200, dark=400)


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("KIVO_CALIBRATION_PATH", str(tmp_path / "cal.json"))
    assert load_thresholds("light") is None  # nothing saved yet
    save_thresholds("light", LightThresholds(dark_below=220, bright_above=610))
    assert load_thresholds("light") == LightThresholds(220, 610)


def test_save_merges_and_keeps_other_sensors(tmp_path, monkeypatch):
    monkeypatch.setenv("KIVO_CALIBRATION_PATH", str(tmp_path / "cal.json"))
    save_thresholds("light", LightThresholds(1, 2))
    save_thresholds("temp", LightThresholds(3, 4))
    assert load_thresholds("light") == LightThresholds(1, 2)
    assert load_thresholds("temp") == LightThresholds(3, 4)


def test_load_returns_none_on_corrupt_file(tmp_path, monkeypatch):
    path = tmp_path / "cal.json"
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setenv("KIVO_CALIBRATION_PATH", str(path))
    assert load_thresholds("light") is None
