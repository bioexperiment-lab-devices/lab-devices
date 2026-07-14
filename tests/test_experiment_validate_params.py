from lab_devices.experiment.blocks import Command
from lab_devices.experiment.validate import validate
from lab_devices.experiment.workflow import Workflow
from tests.experiment_validate_helpers import cmd, diags, wf


def test_unknown_verb_programmatic():
    w = Workflow(schema_version=1, blocks=[Command(device="pump_1", verb="teleport")])
    d = diags(w)
    assert any(x.category == "registry" and "teleport" in x.message for x in d)


def test_unknown_param():
    d = diags(wf([cmd("pump_1", "dispense", {"volume_ml": 1.0, "speed_profile": "fast"})]))
    assert any(x.category == "params" and "speed_profile" in x.message for x in d)


def test_measure_unknown_param():
    """A Measure must reach _check_action's param checks too, not just _check_measure
    (design §12; _check_block deliberately runs both for command and measure blocks)."""
    d = diags(wf(
        [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD",
                       "params": {"exposure_ms": 10}}}],
        streams=["OD"],
    ))
    assert any(x.category == "params" and "exposure_ms" in x.message for x in d)


def test_missing_required_param():
    d = diags(wf([cmd("pump_1", "rotate", {"direction": "forward"})]))
    assert any(x.category == "params" and "speed_ml_min" in x.message for x in d)


def test_int_param_rejects_float_literal():
    d = diags(wf([cmd("densitometer_1", "set_led", {"level": 2.5})]))
    assert any(
        x.category == "params" and "integer" in x.message and x.path == "blocks[0] param 'level'"
        for x in d
    )


def test_bool_param_rejects_int_literal():
    d = diags(wf([cmd("densitometer_1", "set_thermostat", {"enabled": 1})]))
    assert any(x.category == "params" and "boolean" in x.message for x in d)


def test_number_param_rejects_bool_literal():
    d = diags(wf([cmd("pump_1", "dispense", {"volume_ml": True})]))
    assert any(x.category == "params" and "number" in x.message for x in d)


def test_string_param_rejects_number():
    d = diags(wf([cmd("pump_1", "rotate", {"direction": 5, "speed_ml_min": 1.0})]))
    assert any(x.category == "params" and "string" in x.message for x in d)


def test_non_value_param_rejected():
    w = Workflow(schema_version=1, blocks=[
        Command(device="pump_1", verb="dispense", params={"volume_ml": None}),
    ])
    d = diags(w)
    assert any(x.category == "params" and "number" in x.message for x in d)


def test_number_param_rejects_boolean_expression():
    d = diags(wf([cmd("pump_1", "dispense", {"volume_ml": "1 < 2"})]))
    assert any(x.category == "type" and "number" in x.message for x in d)


def test_bool_param_accepts_boolean_expression():
    assert validate(wf([cmd("valve_1", "configure", {"hold_torque": "1 < 2"})])) is None


def test_bool_param_rejects_number_expression():
    d = diags(wf([cmd("valve_1", "configure", {"hold_torque": "1 + 1"})]))
    assert any(x.category == "type" for x in d)


def test_string_param_is_opaque_not_expression():
    # 'forward' parses as a binding ref, but string-kind params are opaque literals:
    # no unbound-binding or type diagnostics may appear, now or in later tasks.
    w = wf([cmd("pump_1", "rotate", {"direction": "forward", "speed_ml_min": 2.0})])
    assert validate(w) is None


def test_string_binding_in_expression_flagged():
    blocks = [
        {"operator_input": {"name": "sel", "type": "enum", "choices": ["a", "b"]}},
        cmd("pump_1", "dispense", {"volume_ml": "sel * 2"}),
    ]
    d = diags(wf(blocks))
    assert any(x.category == "type" and "sel" in x.message for x in d)


def test_invalid_expression_param_programmatic():
    w = Workflow(schema_version=1, blocks=[
        Command(device="pump_1", verb="dispense", params={"volume_ml": "1 +"}),
    ])
    d = diags(w)
    assert any(x.category == "type" and "invalid expression" in x.message for x in d)


def test_declared_binding_number_type_passes():
    blocks = [
        {"operator_input": {"name": "x", "type": "float", "prompt": "x"}},
        cmd("pump_1", "dispense", {"volume_ml": "x * 2"}),
    ]
    assert validate(wf(blocks)) is None


def test_valid_dispense_clean():
    w = wf([cmd(
        "pump_1", "dispense",
        {"volume_ml": 1.5, "speed_ml_min": 3.0, "direction": "reverse"},
    )])
    assert validate(w) is None
