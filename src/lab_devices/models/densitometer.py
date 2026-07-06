"""Densitometer result models. See spec §3.8."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from lab_devices.models.common import RawModel


@dataclass
class Thermostat(RawModel):
    min_c: float | None = None
    max_c: float | None = None


@dataclass
class DensitometerCapabilities(RawModel):
    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {"thermostat": (Thermostat, False)}

    wavelength_nm: int | None = None
    brightness_levels: int | None = None
    thermostat: Thermostat | None = None
    temperature_sensor: str | None = None


@dataclass
class ThermostatState(RawModel):
    enabled: bool | None = None
    target_c: float | None = None
    heating: bool | None = None
    cooling: bool | None = None


@dataclass
class DensitometerStatus(RawModel):
    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {
        "thermostat": (ThermostatState, False)
    }

    state: str | None = None
    job: dict[str, Any] | None = None
    temperature_c: float | None = None
    thermostat: ThermostatState | None = None
    calibration: dict[str, Any] | None = None
    last_measurement: dict[str, Any] | None = None


@dataclass
class MeasureResult(RawModel):
    absorbance: float | None = None
    absorbance_raw: float | None = None
    slope: float | None = None
    blank_slope: float | None = None
    temperature_c: float | None = None
    tube_correction: float | None = None
    seq: int | None = None
    # The optional 20-point sweep (API field "raw", present when include_raw=True) is
    # reachable via `.raw["raw"]`; it is intentionally not a separate typed field because
    # `RawModel.raw` already holds the whole payload.


@dataclass
class Reading(RawModel):
    seq: int | None = None
    uptime_ms: int | None = None
    absorbance: float | None = None
    temperature_c: float | None = None


@dataclass
class ReadingsResult(RawModel):
    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {"readings": (Reading, True)}

    readings: list[Reading] | None = None
    dropped: int | None = None


@dataclass
class ReadRawResult(RawModel):
    intensities: list[float] | None = None
    levels: list[int] | None = None
    temperature_c: float | None = None
