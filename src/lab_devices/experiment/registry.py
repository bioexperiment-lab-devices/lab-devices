"""Command-trait registry: the single source of truth for the narrow subset. See design §3-4."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from lab_devices.experiment.errors import UnknownVerbError

Completion = Literal["job", "immediate"]
StateEffect = Literal["none", "mode"]
Kind = Literal["number", "int", "bool", "string"]


@dataclass(frozen=True)
class ParamSpec:
    """One verb parameter: its scalar kind and whether the verb requires it (design §4)."""

    name: str
    kind: Kind
    required: bool = False


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
    channels: frozenset[str] = field(kw_only=True)
    measurement: bool = field(default=False, kw_only=True)
    params: tuple[ParamSpec, ...] = field(default=(), kw_only=True)


_MOTOR = frozenset({"motor"})
_OPTICS = frozenset({"optics"})
_THERMAL = frozenset({"thermal"})

_REGISTRY: dict[tuple[str, str], Trait] = {
    # pump — one actuator: every verb occupies the motor channel
    ("pump", "dispense"): Trait(
        "job",
        "none",
        channels=_MOTOR,
        params=(
            ParamSpec("volume_ml", "number", required=True),
            ParamSpec("speed_ml_min", "number"),
            ParamSpec("direction", "string"),
            ParamSpec("drop_suckback_ml", "number"),
        ),
    ),
    ("pump", "rotate"): Trait(
        "immediate",
        "mode",
        Teardown("stop"),
        channels=_MOTOR,
        params=(
            ParamSpec("direction", "string", required=True),
            ParamSpec("speed_ml_min", "number", required=True),
        ),
    ),
    ("pump", "stop"): Trait("immediate", "none", channels=_MOTOR),
    ("pump", "set_calibration"): Trait(
        "immediate",
        "none",
        channels=_MOTOR,
        params=(
            ParamSpec("measured_volume_ml", "number"),
            ParamSpec("ml_per_step", "number"),
        ),
    ),
    # valve — one actuator: motor channel
    ("valve", "set_position"): Trait(
        "job",
        "none",
        channels=_MOTOR,
        params=(
            ParamSpec("position", "int", required=True),
            ParamSpec("rotation", "string"),
        ),
    ),
    ("valve", "home"): Trait(
        "immediate",
        "none",
        channels=_MOTOR,
        params=(ParamSpec("position", "int", required=True),),
    ),
    ("valve", "configure"): Trait(
        "immediate",
        "none",
        channels=_MOTOR,
        params=(
            ParamSpec("default_rotation", "string"),
            ParamSpec("hold_torque", "bool"),
        ),
    ),
    ("valve", "stop"): Trait("immediate", "none", channels=_MOTOR),
    # densitometer — optics (LED/measure path) and thermal are independent subsystems
    ("densitometer", "measure"): Trait(
        "job",
        "none",
        channels=_OPTICS,
        measurement=True,
        params=(ParamSpec("include_raw", "bool"),),
    ),
    ("densitometer", "measure_blank"): Trait(
        "job", "none", channels=_OPTICS, measurement=True
    ),
    ("densitometer", "set_led"): Trait(
        "immediate",
        "mode",
        Teardown("set_led", {"level": 0}),
        channels=_OPTICS,
        params=(ParamSpec("level", "int", required=True),),
    ),
    ("densitometer", "set_thermostat"): Trait(
        "immediate",
        "mode",
        Teardown("set_thermostat", {"enabled": False}),
        channels=_THERMAL,
        params=(
            ParamSpec("enabled", "bool", required=True),
            ParamSpec("target_c", "number"),
        ),
    ),
    ("densitometer", "set_tube_correction"): Trait(
        "immediate",
        "none",
        channels=_OPTICS,
        params=(ParamSpec("factor", "number", required=True),),
    ),
    ("densitometer", "calibrate_tube"): Trait(
        "immediate",
        "none",
        channels=_OPTICS,
        params=(ParamSpec("reference_absorbance", "number", required=True),),
    ),
    ("densitometer", "stop"): Trait("immediate", "none", channels=_OPTICS | _THERMAL),
    ("densitometer", "stop_monitoring"): Trait("immediate", "none", channels=_OPTICS),
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


@dataclass(frozen=True)
class ModeAction:
    """A command instance's effect on its device's mode state (design §12)."""

    kind: Literal["open", "close"]
    mode_verb: str


def _params_match(teardown: Teardown, params: Mapping[str, object]) -> bool:
    """Literal match: same keys, equal values, bools only matching bools (False != 0)."""
    if set(params) != set(teardown.params):
        return False
    for key, expected in teardown.params.items():
        actual = params[key]
        if isinstance(expected, bool) != isinstance(actual, bool):
            return False
        if actual != expected:
            return False
    return True


def mode_action(device_id: str, verb: str, params: Mapping[str, object]) -> ModeAction | None:
    """Classify a command instance as a mode-open, a mode-close, or neither (design §12).

    Conservative: any params that do not literally equal the teardown's (including
    expression strings) classify a mode verb as an open.
    """
    dtype = device_type(device_id)
    trait = lookup(device_id, verb)
    if trait.state_effect == "mode":
        assert trait.teardown is not None  # every mode entry declares its teardown
        if trait.teardown.verb == verb and _params_match(trait.teardown, params):
            return ModeAction("close", verb)
        return ModeAction("open", verb)
    for (entry_type, mode_verb), entry in _REGISTRY.items():
        if entry_type != dtype or entry.state_effect != "mode":
            continue
        assert entry.teardown is not None
        if entry.teardown.verb == verb and _params_match(entry.teardown, params):
            return ModeAction("close", mode_verb)
    return None
