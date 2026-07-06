"""Pump result models. See spec §3.6."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from lab_devices.models.common import Range, RawModel


@dataclass
class PumpCapabilities(RawModel):
    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {"speed_ml_min": (Range, False)}

    channels: int | None = None
    speed_ml_min: Range | None = None
    supports_gradient: bool | None = None
    supports_drop_suckback: bool | None = None
    calibration_unverified: bool | None = None


@dataclass
class Calibration(RawModel):
    ml_per_step: float | None = None
    set_at_uptime_ms: int | None = None


@dataclass
class PumpStatus(RawModel):
    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {"calibration": (Calibration, False)}

    state: str | None = None
    job: dict[str, Any] | None = None
    direction: str | None = None
    speed_ml_min: float | None = None
    dispensed_ml: float | None = None
    calibration: Calibration | None = None


@dataclass
class DispenseResult(RawModel):
    dispensed_ml: float | None = None
    duration_s: float | None = None
    mean_speed_ml_min: float | None = None
    suckback_ml: float | None = None


@dataclass
class CalibrationRunResult(RawModel):
    steps: int | None = None
    duration_s: float | None = None
