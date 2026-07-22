"""Tests for the public verb/expression catalog accessors (webapp design §4.4)."""

import json

from lab_devices.experiment import expression_functions, verb_catalog


def test_catalog_covers_all_device_types():
    assert set(verb_catalog()) == {"pump", "valve", "densitometer"}


def test_dispense_entry_exact():
    dispense = verb_catalog()["pump"]["dispense"]
    assert dispense["kind"] == "command"
    assert dispense["result_field"] is None
    assert dispense["params"][0] == {"name": "volume_ml", "type": "number", "required": True}
    assert [p["name"] for p in dispense["params"]] == [
        "volume_ml",
        "speed_ml_min",
        "direction",
        "drop_suckback_ml",
    ]


def test_measure_verbs_marked_with_result_field():
    dens = verb_catalog()["densitometer"]
    assert dens["measure"]["kind"] == "measure"
    assert dens["measure"]["result_field"] == "absorbance"
    assert dens["measure_blank"]["kind"] == "measure"
    assert dens["measure_blank"]["result_field"] == "slope"
    assert dens["set_led"]["kind"] == "command"


def test_no_param_verb_has_empty_params():
    assert verb_catalog()["valve"]["stop"]["params"] == []


def test_expression_functions_sorted_and_windows():
    fns = expression_functions()
    assert fns["functions"] == ["count", "last", "max", "mean", "min"]
    assert fns["windows"] == ["all", "last_n", "duration"]


def test_catalog_is_json_serializable():
    json.dumps({"device_types": verb_catalog(), "expression": expression_functions()})


def test_catalog_exposes_retry_safe():
    catalog = verb_catalog()
    assert catalog["densitometer"]["measure"]["retry_safe"] is True
    assert catalog["pump"]["dispense"]["retry_safe"] is False


def test_catalog_declares_enum_values_for_closed_string_params():
    cat = verb_catalog()
    rotate = {p["name"]: p for p in cat["pump"]["rotate"]["params"]}
    assert rotate["direction"]["values"] == ["forward", "reverse"]
    valve = {p["name"]: p for p in cat["valve"]["set_position"]["params"]}
    assert valve["rotation"]["values"] == ["shortest", "direct", "wrap"]
    configure = {p["name"]: p for p in cat["valve"]["configure"]["params"]}
    assert configure["default_rotation"]["values"] == ["shortest", "direct", "wrap"]
    dispense = {p["name"]: p for p in cat["pump"]["dispense"]["params"]}
    assert dispense["direction"]["values"] == ["forward", "reverse"]


def test_catalog_omits_values_key_for_open_string_params():
    cat = verb_catalog()
    volume = {p["name"]: p for p in cat["pump"]["dispense"]["params"]}["volume_ml"]
    assert "values" not in volume


def test_catalog_declares_param_defaults():
    cat = verb_catalog()
    dispense = {p["name"]: p for p in cat["pump"]["dispense"]["params"]}
    assert dispense["direction"]["default"] == "forward"
    rotate = {p["name"]: p for p in cat["pump"]["rotate"]["params"]}
    assert rotate["direction"]["default"] == "forward"
    thermo = {p["name"]: p for p in cat["densitometer"]["set_thermostat"]["params"]}
    assert thermo["enabled"]["default"] is True
    meas = {p["name"]: p for p in cat["densitometer"]["measure"]["params"]}
    assert meas["include_raw"]["default"] is False


def test_catalog_declares_on_omit():
    cat = verb_catalog()
    setpos = {p["name"]: p for p in cat["valve"]["set_position"]["params"]}
    assert setpos["rotation"]["on_omit"] == "default"
    assert "default" not in setpos["rotation"]
    conf = {p["name"]: p for p in cat["valve"]["configure"]["params"]}
    assert conf["default_rotation"]["on_omit"] == "unchanged"
    assert conf["hold_torque"]["on_omit"] == "unchanged"


def test_catalog_omits_default_and_on_omit_when_absent():
    volume = {p["name"]: p for p in verb_catalog()["pump"]["dispense"]["params"]}["volume_ml"]
    assert "default" not in volume and "on_omit" not in volume


def test_catalog_exposes_read_temperature_measurement():
    dens = verb_catalog()["densitometer"]
    assert dens["read_temperature"]["kind"] == "measure"
    assert dens["read_temperature"]["result_field"] == "temperature_c"
    assert dens["read_temperature"]["params"] == []
