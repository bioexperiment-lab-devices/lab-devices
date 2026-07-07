import pytest

from lab_devices.experiment.errors import UnknownVerbError
from lab_devices.experiment.registry import Teardown, device_type, lookup


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
