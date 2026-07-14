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
