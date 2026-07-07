"""Command-trait registry: the single source of truth for the narrow subset. See design §3-4."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from lab_devices.experiment.errors import UnknownVerbError

Completion = Literal["job", "immediate"]
StateEffect = Literal["none", "mode"]


@dataclass
class Teardown:
    """How to close a continuous mode (design §4)."""

    verb: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trait:
    completion: Completion
    state_effect: StateEffect
    teardown: Teardown | None = None


_REGISTRY: dict[tuple[str, str], Trait] = {
    # pump
    ("pump", "dispense"): Trait("job", "none"),
    ("pump", "start_calibration"): Trait("job", "none"),
    ("pump", "rotate"): Trait("immediate", "mode", Teardown("stop")),
    ("pump", "stop"): Trait("immediate", "none"),
    ("pump", "set_calibration"): Trait("immediate", "none"),
    # valve
    ("valve", "set_position"): Trait("job", "none"),
    ("valve", "home"): Trait("immediate", "none"),
    ("valve", "configure"): Trait("immediate", "none"),
    ("valve", "stop"): Trait("immediate", "none"),
    # densitometer
    ("densitometer", "measure"): Trait("job", "none"),
    ("densitometer", "measure_blank"): Trait("job", "none"),
    ("densitometer", "set_led"): Trait("immediate", "mode", Teardown("set_led", {"level": 0})),
    ("densitometer", "set_thermostat"): Trait(
        "immediate", "mode", Teardown("set_thermostat", {"enabled": False})
    ),
    ("densitometer", "set_tube_correction"): Trait("immediate", "none"),
    ("densitometer", "calibrate_tube"): Trait("immediate", "none"),
    ("densitometer", "stop"): Trait("immediate", "none"),
    ("densitometer", "stop_monitoring"): Trait("immediate", "none"),
}


def device_type(device_id: str) -> str:
    """Mirror the core's Device.type derivation."""
    return device_id.rsplit("_", 1)[0]


def lookup(device_id: str, verb: str) -> Trait:
    key = (device_type(device_id), verb)
    try:
        return _REGISTRY[key]
    except KeyError:
        raise UnknownVerbError(
            f"no registry entry for device-type {key[0]!r} verb {verb!r}"
        ) from None
