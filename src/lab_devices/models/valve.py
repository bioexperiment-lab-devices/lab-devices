"""Distribution valve result models. See spec §3.7."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from lab_devices.models.common import RawModel


@dataclass
class ValveCapabilities(RawModel):
    positions: int | None = None
    rotation_modes: list[str] | None = None
    seconds_per_position: float | None = None


@dataclass
class ValveConfig(RawModel):
    default_rotation: str | None = None
    hold_torque: bool | None = None


@dataclass
class ValveStatus(RawModel):
    state: str | None = None
    homed: bool | None = None
    position: int | None = None
    target_position: int | None = None
    job: dict[str, Any] | None = None
    config: ValveConfig | None = None

    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {"config": (ValveConfig, False)}


@dataclass
class ValveMoveResult(RawModel):
    position: int | None = None
    from_position: int | None = None
    direction: str | None = None
    duration_s: float | None = None
