import pytest

from lab_devices.experiment import registry
from lab_devices.experiment.errors import UnknownVerbError
from lab_devices.experiment.registry import (
    _REGISTRY,
    ModeAction,
    ParamSpec,
    Teardown,
    lookup,
    mode_action,
)


def test_job_command_trait():
    t = lookup("pump", "dispense")
    assert t.completion == "job"
    assert t.state_effect == "none"
    assert t.teardown is None


def test_continuous_mode_has_teardown():
    assert lookup("pump", "rotate").teardown == Teardown("stop")
    assert lookup("densitometer", "set_led").teardown == Teardown("set_led", {"level": 0})
    assert lookup("densitometer", "set_thermostat").teardown == Teardown(
        "set_thermostat", {"enabled": False}
    )


def test_instant_config_trait():
    t = lookup("valve", "configure")
    assert t.completion == "immediate"
    assert t.state_effect == "none"


def test_unknown_verb_raises():
    with pytest.raises(UnknownVerbError):
        lookup("pump", "teleport")
    with pytest.raises(UnknownVerbError):
        lookup("toaster", "dispense")


def test_every_entry_declares_channels():
    for key, trait in _REGISTRY.items():
        assert trait.channels, f"{key} has no channels"


def test_channel_table():
    assert lookup("pump", "dispense").channels == frozenset({"motor"})
    assert lookup("pump", "rotate").channels == frozenset({"motor"})
    assert lookup("pump", "stop").channels == frozenset({"motor"})
    assert lookup("valve", "set_position").channels == frozenset({"motor"})
    assert lookup("valve", "configure").channels == frozenset({"motor"})
    assert lookup("densitometer", "measure").channels == frozenset({"optics"})
    assert lookup("densitometer", "set_led").channels == frozenset({"optics"})
    assert lookup("densitometer", "set_tube_correction").channels == frozenset({"optics"})
    assert lookup("densitometer", "set_thermostat").channels == frozenset({"thermal"})
    assert lookup("densitometer", "stop").channels == frozenset({"optics", "thermal"})
    assert lookup("densitometer", "stop_monitoring").channels == frozenset({"optics"})


def test_measurement_flags():
    measuring = {key for key, t in _REGISTRY.items() if t.measurement}
    assert measuring == {("densitometer", "measure"), ("densitometer", "measure_blank")}
    for key in measuring:
        assert _REGISTRY[key].completion == "job"


def test_param_specs_dispense():
    specs = {s.name: s for s in lookup("pump", "dispense").params}
    assert specs["volume_ml"] == ParamSpec("volume_ml", "number", required=True)
    assert specs["speed_ml_min"] == ParamSpec("speed_ml_min", "number")
    assert specs["direction"].kind == "string" and not specs["direction"].required
    assert set(specs) == {"volume_ml", "speed_ml_min", "direction", "drop_suckback_ml"}


def test_param_specs_spot_checks():
    rotate = {s.name: s for s in lookup("pump", "rotate").params}
    assert rotate["direction"] == ParamSpec(
        "direction", "string", required=True, values=("forward", "reverse")
    )
    assert rotate["speed_ml_min"] == ParamSpec("speed_ml_min", "number", required=True)
    setpos = {s.name: s for s in lookup("valve", "set_position").params}
    assert setpos["position"] == ParamSpec("position", "int", required=True)
    assert setpos["rotation"].kind == "string"
    thermo = {s.name: s for s in lookup("densitometer", "set_thermostat").params}
    assert thermo["enabled"] == ParamSpec("enabled", "bool", required=True)
    assert thermo["target_c"].kind == "number"
    led = {s.name: s for s in lookup("densitometer", "set_led").params}
    assert led["level"] == ParamSpec("level", "int", required=True)
    assert lookup("pump", "stop").params == ()
    assert lookup("valve", "home").params == (ParamSpec("position", "int", required=True),)
    conf = {s.name: s for s in lookup("valve", "configure").params}
    assert conf["hold_torque"].kind == "bool"


def test_teardown_verbs_are_registered():
    for (dtype, _), trait in _REGISTRY.items():
        if trait.teardown is not None:
            assert (dtype, trait.teardown.verb) in _REGISTRY


def test_mode_action_open_close_by_teardown_comparison():
    assert mode_action(
        "pump", "rotate", {"direction": "forward", "speed_ml_min": 2.0}
    ) == ModeAction("open", "rotate")
    assert mode_action("pump", "stop", {}) == ModeAction("close", "rotate")
    assert mode_action("valve", "stop", {}) is None
    assert mode_action("densitometer", "set_led", {"level": 5}) == ModeAction("open", "set_led")
    assert mode_action("densitometer", "set_led", {"level": 0}) == ModeAction("close", "set_led")
    assert mode_action(
        "densitometer", "set_thermostat", {"enabled": False}
    ) == ModeAction("close", "set_thermostat")
    assert mode_action(
        "densitometer", "set_thermostat", {"enabled": True, "target_c": 37.0}
    ) == ModeAction("open", "set_thermostat")
    assert mode_action("pump", "dispense", {"volume_ml": 1.0}) is None
    assert mode_action("densitometer", "measure", {}) is None
    assert mode_action("densitometer", "stop", {}) is None


def test_mode_action_conservative_cases():
    # An expression-valued level can be 0 at runtime, but statically it is an open.
    assert mode_action(
        "densitometer", "set_led", {"level": "x - x"}
    ) == ModeAction("open", "set_led")
    # bool is not int: set_led(level=False) does not match teardown level=0.
    assert mode_action(
        "densitometer", "set_led", {"level": False}
    ) == ModeAction("open", "set_led")
    # Extra params beyond the teardown's do not match: still an open.
    assert mode_action(
        "densitometer", "set_thermostat", {"enabled": False, "target_c": 20.0}
    ) == ModeAction("open", "set_thermostat")
    # A stop with unexpected params does not match the bare teardown: not a close.
    assert mode_action("pump", "stop", {"force": True}) is None


def test_mode_teardown_channel_invariant():
    """The validator's close-skips-conflict-scan is sound only under this invariant:
    every mode's teardown verb occupies exactly the mode's own channels."""
    for (dtype, _verb), trait in _REGISTRY.items():
        if trait.state_effect != "mode":
            continue
        assert trait.teardown is not None
        teardown_trait = _REGISTRY[(dtype, trait.teardown.verb)]
        assert teardown_trait.channels == trait.channels


def test_mode_channels_pairwise_disjoint_per_device_type():
    """Second half of the close-skips-conflict-scan invariant: no two modes of one
    device type may share a channel (else a close could hide inside another mode)."""
    by_type: dict = {}
    for (dtype, _verb), trait in _REGISTRY.items():
        if trait.state_effect == "mode":
            by_type.setdefault(dtype, []).append(trait.channels)
    for dtype, channel_sets in by_type.items():
        for i in range(len(channel_sets)):
            for j in range(i + 1, len(channel_sets)):
                assert not (channel_sets[i] & channel_sets[j]), dtype


def test_stop_channels_cover_every_mode_on_the_device_type():
    """The retry's orphan-cancel is a device.stop() (Job.cancel() IS device.stop()), and its
    guard -- execute._modes_a_stop_would_close -- only refuses the retry for open modes whose
    channels INTERSECT the device's `stop` channels. That channel filter is safe only while a
    stop cannot close a mode it does not name: today every densitometer stop covers optics |
    thermal, so it does. Narrow densitometer.stop to optics and the guard would happily stop the
    device to clear an orphaned measure, silently killing the thermostat -- exactly the failure
    the guard exists to prevent. Pin the invariant so a future narrow stop trips a test here.

    A device type with NO stop verb is fine: the guard assumes the worst (every open mode on the
    device) rather than the best."""
    for (dtype, verb), trait in _REGISTRY.items():
        if trait.state_effect != "mode":
            continue
        stop = _REGISTRY.get((dtype, "stop"))
        if stop is None:
            continue
        assert trait.channels & stop.channels, (dtype, verb)


def test_mode_opening_traits_complete_immediately():
    """execute._dispatch_action calls register_open with NO await between releasing the wire
    lock and that call -- true today only because every mode-opening trait (state_effect ==
    "mode") has completion == "immediate", so the `if trait.completion == "job": ... await
    _await_job(...)` branch never executes on a mode-opening dispatch. That absence of an
    await is exactly what makes _clear_orphaned_job's in-lock open-mode check sound (see the
    comment above register_open in execute.py): the guard takes ctx.lock(device) and reads
    ctx.occupancy, trusting that any sibling's register_open has already run by the time it
    could ever be granted that same lock.

    If a mode-opening verb ever became completion == "job", _dispatch_action would await
    _await_job(...) in that exact gap -- and _await_job itself takes and releases the wire
    lock on every poll. The guard could then acquire the lock DURING that job wait, see zero
    open modes (registration hasn't happened yet), and issue a stop that silently kills the
    mode being opened: the identical Critical bug design 2026-07-14 §3.3 fixed, reopened by a
    change in a completely different function. Pin the invariant so that change trips a test
    here instead of a live thermostat."""
    for (dtype, verb), trait in _REGISTRY.items():
        if trait.state_effect == "mode":
            assert trait.completion == "immediate", (dtype, verb)


def test_measurement_verbs_declare_result_field():
    assert lookup("densitometer", "measure").result_field == "absorbance"
    assert lookup("densitometer", "measure_blank").result_field == "slope"


def test_result_field_only_on_measurement_verbs():
    from lab_devices.experiment.registry import _REGISTRY

    for (dtype, verb), trait in _REGISTRY.items():
        if trait.measurement:
            assert trait.result_field is not None, (dtype, verb)
        else:
            assert trait.result_field is None, (dtype, verb)


def test_dispense_is_not_retry_safe():
    assert lookup("pump", "dispense").retry_safe is False


def test_reads_and_absolute_setters_are_retry_safe():
    assert lookup("densitometer", "measure").retry_safe is True
    assert lookup("densitometer", "measure_blank").retry_safe is True
    assert lookup("densitometer", "set_thermostat").retry_safe is True
    assert lookup("valve", "set_position").retry_safe is True
    assert lookup("valve", "home").retry_safe is True
    assert lookup("pump", "stop").retry_safe is True


def test_relative_and_hidden_state_verbs_are_not_retry_safe():
    # dispense moves a *relative* volume: a retry after a partial dispense double-doses.
    assert lookup("pump", "dispense").retry_safe is False
    # rotate opens an unbounded fluid-moving mode; it needs an explicit author opt-in.
    assert lookup("pump", "rotate").retry_safe is False
    # calibrate_tube derives its factor from the *last measurement*, not from its params.
    assert lookup("densitometer", "calibrate_tube").retry_safe is False


# Every verb, classified deliberately. A verb added without a decision defaults to False
# and fails this test, which is the point: nobody gets a silent retry by omission.
_RETRY_SAFE = {
    ("pump", "dispense"): False,
    ("pump", "rotate"): False,
    ("pump", "stop"): True,
    ("pump", "set_calibration"): True,
    ("valve", "set_position"): True,
    ("valve", "home"): True,
    ("valve", "configure"): True,
    ("valve", "stop"): True,
    ("densitometer", "measure"): True,
    ("densitometer", "measure_blank"): True,
    ("densitometer", "set_led"): True,
    ("densitometer", "set_thermostat"): True,
    ("densitometer", "set_tube_correction"): True,
    ("densitometer", "calibrate_tube"): False,
    ("densitometer", "stop"): True,
    ("densitometer", "stop_monitoring"): True,
}


def test_every_registry_verb_declares_its_retry_safety():
    assert {key: trait.retry_safe for key, trait in _REGISTRY.items()} == _RETRY_SAFE


def test_lookup_takes_a_device_type_not_an_id():
    """The discriminating assertion is the SECOND one. `lookup("pump", ...)` passes today
    too, because rsplit("_", 1) on a string with no underscore returns it unchanged --
    a probe that only asserts the positive case is vacuous here."""
    assert lookup("pump", "dispense").completion == "job"
    with pytest.raises(UnknownVerbError):
        lookup("pump_1", "dispense")


def test_mode_action_takes_a_device_type_not_an_id():
    assert mode_action("pump", "stop", {}) == ModeAction("close", "rotate")
    with pytest.raises(UnknownVerbError):
        mode_action("pump_1", "stop", {})


def test_device_type_helper_is_deleted():
    """Roles carry their type in the declaration; deriving it from an id is the convention
    this increment removes (design 2026-07-20 §5.2)."""
    assert not hasattr(registry, "device_type")


def test_device_types_is_derived_from_the_registry():
    assert registry.DEVICE_TYPES == frozenset({"pump", "valve", "densitometer"})
    assert registry.DEVICE_TYPES == frozenset(dtype for dtype, _verb in _REGISTRY)
    assert isinstance(registry.DEVICE_TYPES, frozenset)
