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
    """One verb parameter: its scalar kind and whether the verb requires it (design §4).
    `values` closes a string param over an explicit literal set (an enum): the device
    accepts exactly these spellings, so the validator can reject the rest at load."""

    name: str
    kind: Kind
    required: bool = False
    values: tuple[str, ...] | None = None


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
    result_field: str | None = field(default=None, kw_only=True)
    params: tuple[ParamSpec, ...] = field(default=(), kw_only=True)
    retry_safe: bool = field(default=False, kw_only=True)
    # True iff re-issuing this verb with the same params is idempotent: pure reads and
    # absolute setters land the hardware in the same state. False for relative actions
    # (pump.dispense): a retry after a partial dispense double-doses the culture
    # (design 2026-07-14 §4). Default False — a verb added later is conservative until
    # someone thinks about it.


_MOTOR = frozenset({"motor"})
_OPTICS = frozenset({"optics"})
_THERMAL = frozenset({"thermal"})

_REGISTRY: dict[tuple[str, str], Trait] = {
    # pump — one actuator: every verb occupies the motor channel
    # NOT retry_safe: volume_ml is *relative*. A retry after a partial dispense delivers a
    # second dose on top of what already went in — a silent double-dose of the culture.
    ("pump", "dispense"): Trait(
        "job",
        "none",
        channels=_MOTOR,
        params=(
            ParamSpec("volume_ml", "number", required=True),
            ParamSpec("speed_ml_min", "number"),
            ParamSpec("direction", "string", values=("forward", "reverse")),
            ParamSpec("drop_suckback_ml", "number"),
        ),
    ),
    # NOT retry_safe: re-issuing rotate lands the same *state* (direction/speed), but it opens
    # unbounded fluid delivery whose dose is set by how long it runs, not by its params. An
    # auto-retry must not start liquid moving into a culture without an author's opt-in.
    ("pump", "rotate"): Trait(
        "immediate",
        "mode",
        Teardown("stop"),
        channels=_MOTOR,
        params=(
            ParamSpec("direction", "string", required=True, values=("forward", "reverse")),
            ParamSpec("speed_ml_min", "number", required=True),
        ),
    ),
    # Safe-state primitive; firmware documents it as "always succeeds" (§3.6). Stopping twice
    # is stopped: plain idempotence — NOT a finalization safeguard. finalize.py never consults
    # retry_safe; its safe-state sweep is unconditional and best-effort regardless
    # (finalize.py:46). retry_safe only governs the executor's normal-path dispatch, where
    # `stop` can appear as an ordinary workflow block.
    ("pump", "stop"): Trait("immediate", "none", channels=_MOTOR, retry_safe=True),
    # Absolute write of ml_per_step (either directly, or derived from a fixed calibration
    # run's step count); re-issuing the same params persists the same value.
    ("pump", "set_calibration"): Trait(
        "immediate",
        "none",
        channels=_MOTOR,
        retry_safe=True,
        params=(
            ParamSpec("measured_volume_ml", "number"),
            ParamSpec("ml_per_step", "number"),
        ),
    ),
    # valve — one actuator: motor channel
    # Absolute target position; requesting the current position completes instantly.
    ("valve", "set_position"): Trait(
        "job",
        "none",
        channels=_MOTOR,
        retry_safe=True,
        params=(
            ParamSpec("position", "int", required=True),
            ParamSpec("rotation", "string", values=("shortest", "direct", "wrap")),
        ),
    ),
    # Declares the current physical position (no motion) — pure absolute state write.
    ("valve", "home"): Trait(
        "immediate",
        "none",
        channels=_MOTOR,
        retry_safe=True,
        params=(ParamSpec("position", "int", required=True),),
    ),
    # Absolute per-field config write; omitted fields are unchanged.
    ("valve", "configure"): Trait(
        "immediate",
        "none",
        channels=_MOTOR,
        retry_safe=True,
        params=(
            ParamSpec("default_rotation", "string", values=("shortest", "direct", "wrap")),
            ParamSpec("hold_torque", "bool"),
        ),
    ),
    # Safe-state primitive; a no-op when already idle.
    ("valve", "stop"): Trait("immediate", "none", channels=_MOTOR, retry_safe=True),
    # densitometer — optics (LED/measure path) and thermal are independent subsystems
    # Pure read: takes a fresh reading and actuates nothing.
    ("densitometer", "measure"): Trait(
        "job",
        "none",
        channels=_OPTICS,
        measurement=True,
        result_field="absorbance",
        retry_safe=True,
        params=(ParamSpec("include_raw", "bool"),),
    ),
    # Re-measures the blank and overwrites the stored baseline: last-write-wins, no accumulation.
    ("densitometer", "measure_blank"): Trait(
        "job", "none", channels=_OPTICS, measurement=True, result_field="slope", retry_safe=True
    ),
    # Absolute LED level (0-20), diagnostic: no dosing, no accumulation.
    ("densitometer", "set_led"): Trait(
        "immediate",
        "mode",
        Teardown("set_led", {"level": 0}),
        channels=_OPTICS,
        retry_safe=True,
        params=(ParamSpec("level", "int", required=True),),
    ),
    # Absolute setpoint (enabled + target_c): the thermostat converges to the same state.
    ("densitometer", "set_thermostat"): Trait(
        "immediate",
        "mode",
        Teardown("set_thermostat", {"enabled": False}),
        channels=_THERMAL,
        retry_safe=True,
        params=(
            ParamSpec("enabled", "bool", required=True),
            ParamSpec("target_c", "number"),
        ),
    ),
    # Absolute correction factor (0.5-2.0): setting the same factor twice persists the same value.
    ("densitometer", "set_tube_correction"): Trait(
        "immediate",
        "none",
        channels=_OPTICS,
        retry_safe=True,
        params=(ParamSpec("factor", "number", required=True),),
    ),
    # NOT retry_safe: unlike set_tube_correction, this derives the factor from the *last
    # measurement* (hidden device state, not its params). A retry can consume a different
    # reading than the first attempt did, silently re-calibrating the OD that drives dosing.
    ("densitometer", "calibrate_tube"): Trait(
        "immediate",
        "none",
        channels=_OPTICS,
        params=(ParamSpec("reference_absorbance", "number", required=True),),
    ),
    # Cancels job/monitoring, LED off; firmware documents it as "always succeeds" (§3.8) —
    # plain idempotence. (Not a finalization safeguard: finalize.py never consults retry_safe.)
    ("densitometer", "stop"): Trait(
        "immediate", "none", channels=_OPTICS | _THERMAL, retry_safe=True
    ),
    # Ends monitoring mode. Retry-safe because it cannot accumulate state, not because §3.8
    # promises a no-op when idle — unlike `stop`, it isn't documented as "always succeeds", so
    # a re-issue while not monitoring could surface a spurious error rather than a clean no-op.
    ("densitometer", "stop_monitoring"): Trait(
        "immediate", "none", channels=_OPTICS, retry_safe=True
    ),
}


DEVICE_TYPES: frozenset[str] = frozenset(dtype for dtype, _verb in _REGISTRY)


def lookup(dtype: str, verb: str) -> Trait:
    """Trait for a (device TYPE, verb) pair. The caller supplies the type -- read it from
    `workflow.roles[name].type` (design 2026-07-20 §5.2)."""
    try:
        return _REGISTRY[(dtype, verb)]
    except KeyError:
        raise UnknownVerbError(
            f"no registry entry for device-type {dtype!r} verb {verb!r}"
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


def mode_action(dtype: str, verb: str, params: Mapping[str, object]) -> ModeAction | None:
    """Classify a command instance as a mode-open, a mode-close, or neither (design §12).

    Conservative: any params that do not literally equal the teardown's (including
    expression strings) classify a mode verb as an open.
    """
    trait = lookup(dtype, verb)
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
