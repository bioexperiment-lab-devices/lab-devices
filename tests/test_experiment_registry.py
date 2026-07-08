import pytest

from lab_devices.experiment.errors import UnknownVerbError
from lab_devices.experiment.registry import (
    _REGISTRY,
    ModeAction,
    ParamSpec,
    Teardown,
    device_type,
    lookup,
    mode_action,
)


def test_device_type_strips_index():
    assert device_type("pump_1") == "pump"
    assert device_type("densitometer_12") == "densitometer"


def test_job_command_trait():
    t = lookup("pump_1", "dispense")
    assert t.completion == "job"
    assert t.state_effect == "none"
    assert t.teardown is None


def test_continuous_mode_has_teardown():
    assert lookup("pump_1", "rotate").teardown == Teardown("stop")
    assert lookup("densitometer_1", "set_led").teardown == Teardown("set_led", {"level": 0})
    assert lookup("densitometer_1", "set_thermostat").teardown == Teardown(
        "set_thermostat", {"enabled": False}
    )


def test_instant_config_trait():
    t = lookup("valve_1", "configure")
    assert t.completion == "immediate"
    assert t.state_effect == "none"


def test_unknown_verb_raises():
    with pytest.raises(UnknownVerbError):
        lookup("pump_1", "teleport")
    with pytest.raises(UnknownVerbError):
        lookup("toaster_1", "dispense")


def test_every_entry_declares_channels():
    for key, trait in _REGISTRY.items():
        assert trait.channels, f"{key} has no channels"


def test_channel_table():
    assert lookup("pump_1", "dispense").channels == frozenset({"motor"})
    assert lookup("pump_1", "rotate").channels == frozenset({"motor"})
    assert lookup("pump_1", "stop").channels == frozenset({"motor"})
    assert lookup("valve_1", "set_position").channels == frozenset({"motor"})
    assert lookup("valve_1", "configure").channels == frozenset({"motor"})
    assert lookup("densitometer_1", "measure").channels == frozenset({"optics"})
    assert lookup("densitometer_1", "set_led").channels == frozenset({"optics"})
    assert lookup("densitometer_1", "set_tube_correction").channels == frozenset({"optics"})
    assert lookup("densitometer_1", "set_thermostat").channels == frozenset({"thermal"})
    assert lookup("densitometer_1", "stop").channels == frozenset({"optics", "thermal"})
    assert lookup("densitometer_1", "stop_monitoring").channels == frozenset({"optics"})


def test_measurement_flags():
    measuring = {key for key, t in _REGISTRY.items() if t.measurement}
    assert measuring == {("densitometer", "measure"), ("densitometer", "measure_blank")}
    for key in measuring:
        assert _REGISTRY[key].completion == "job"


def test_param_specs_dispense():
    specs = {s.name: s for s in lookup("pump_1", "dispense").params}
    assert specs["volume_ml"] == ParamSpec("volume_ml", "number", required=True)
    assert specs["speed_ml_min"] == ParamSpec("speed_ml_min", "number")
    assert specs["direction"].kind == "string" and not specs["direction"].required
    assert set(specs) == {"volume_ml", "speed_ml_min", "direction", "drop_suckback_ml"}


def test_param_specs_spot_checks():
    rotate = {s.name: s for s in lookup("pump_1", "rotate").params}
    assert rotate["direction"] == ParamSpec("direction", "string", required=True)
    assert rotate["speed_ml_min"] == ParamSpec("speed_ml_min", "number", required=True)
    setpos = {s.name: s for s in lookup("valve_1", "set_position").params}
    assert setpos["position"] == ParamSpec("position", "int", required=True)
    assert setpos["rotation"].kind == "string"
    thermo = {s.name: s for s in lookup("densitometer_1", "set_thermostat").params}
    assert thermo["enabled"] == ParamSpec("enabled", "bool", required=True)
    assert thermo["target_c"].kind == "number"
    led = {s.name: s for s in lookup("densitometer_1", "set_led").params}
    assert led["level"] == ParamSpec("level", "int", required=True)
    assert lookup("pump_1", "stop").params == ()
    assert lookup("valve_1", "home").params == (ParamSpec("position", "int", required=True),)
    conf = {s.name: s for s in lookup("valve_1", "configure").params}
    assert conf["hold_torque"].kind == "bool"


def test_teardown_verbs_are_registered():
    for (dtype, _), trait in _REGISTRY.items():
        if trait.teardown is not None:
            assert (dtype, trait.teardown.verb) in _REGISTRY


def test_mode_action_open_close_by_teardown_comparison():
    assert mode_action(
        "pump_1", "rotate", {"direction": "forward", "speed_ml_min": 2.0}
    ) == ModeAction("open", "rotate")
    assert mode_action("pump_1", "stop", {}) == ModeAction("close", "rotate")
    assert mode_action("valve_1", "stop", {}) is None
    assert mode_action("densitometer_1", "set_led", {"level": 5}) == ModeAction("open", "set_led")
    assert mode_action("densitometer_1", "set_led", {"level": 0}) == ModeAction("close", "set_led")
    assert mode_action(
        "densitometer_1", "set_thermostat", {"enabled": False}
    ) == ModeAction("close", "set_thermostat")
    assert mode_action(
        "densitometer_1", "set_thermostat", {"enabled": True, "target_c": 37.0}
    ) == ModeAction("open", "set_thermostat")
    assert mode_action("pump_1", "dispense", {"volume_ml": 1.0}) is None
    assert mode_action("densitometer_1", "measure", {}) is None
    assert mode_action("densitometer_1", "stop", {}) is None


def test_mode_action_conservative_cases():
    # An expression-valued level can be 0 at runtime, but statically it is an open.
    assert mode_action(
        "densitometer_1", "set_led", {"level": "x - x"}
    ) == ModeAction("open", "set_led")
    # bool is not int: set_led(level=False) does not match teardown level=0.
    assert mode_action(
        "densitometer_1", "set_led", {"level": False}
    ) == ModeAction("open", "set_led")
    # Extra params beyond the teardown's do not match: still an open.
    assert mode_action(
        "densitometer_1", "set_thermostat", {"enabled": False, "target_c": 20.0}
    ) == ModeAction("open", "set_thermostat")
    # A stop with unexpected params does not match the bare teardown: not a close.
    assert mode_action("pump_1", "stop", {"force": True}) is None


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
