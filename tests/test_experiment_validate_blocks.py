from lab_devices.experiment.blocks import Loop, Measure
from lab_devices.experiment.validate import validate
from lab_devices.experiment.workflow import Workflow
from tests.experiment_validate_helpers import MEASURE_OD, cmd, diags, wf


def test_loop_count_zero():
    d = diags(wf([{"loop": {"count": 0, "body": [MEASURE_OD]}}], streams=["OD"]))
    assert any(x.category == "block" and ">= 1" in x.message for x in d)


def test_loop_count_bool_and_str():
    w = Workflow(schema_version=1, blocks=[Loop(count=True, body=[])])
    assert any("integer" in x.message for x in diags(w))
    w2 = Workflow(schema_version=1, blocks=[Loop(count="5", body=[])])
    assert any("integer" in x.message for x in diags(w2))


def test_loop_count_and_until_both():
    w = Workflow(schema_version=1, blocks=[Loop(count=2, until="1 < 2", body=[])])
    assert any("exactly one" in x.message for x in diags(w))


def test_loop_neither_count_nor_until():
    w = Workflow(schema_version=1, blocks=[Loop(body=[])])
    assert any("exactly one" in x.message for x in diags(w))


def test_pace_only_with_count():
    d = diags(wf(
        [{"loop": {"until": "count(OD) > 3", "pace": "30s", "body": [MEASURE_OD]}}],
        streams=["OD"],
    ))
    assert any("pace" in x.message for x in d)


def test_pace_with_count_ok():
    w = wf([{"loop": {"count": 3, "pace": "30s", "body": [MEASURE_OD]}}], streams=["OD"])
    assert validate(w) is None


def test_invalid_check_programmatic():
    w = Workflow(
        schema_version=1, blocks=[Loop(until="1 < 2", check="sometimes", body=[])]
    )
    assert any("check" in x.message for x in diags(w))


def test_branch_condition_must_be_boolean():
    d = diags(wf([{"branch": {"if": "1 + 1", "then": [MEASURE_OD]}}], streams=["OD"]))
    assert any(x.category == "type" and "boolean" in x.message for x in d)


def test_until_condition_must_be_boolean():
    d = diags(wf(
        [{"loop": {"until": "count(OD) + 1", "check": "after", "body": [MEASURE_OD]}}],
        streams=["OD"],
    ))
    assert any(x.category == "type" and "boolean" in x.message for x in d)


def test_operator_input_bad_type():
    d = diags(wf([{"operator_input": {"name": "x", "type": "string"}}]))
    assert any(x.category == "block" and "float, int, enum, bool" in x.message for x in d)


def test_enum_requires_choices():
    d = diags(wf([{"operator_input": {"name": "x", "type": "enum"}}]))
    assert any("choices" in x.message for x in d)


def test_choices_only_for_enum():
    d = diags(wf([{"operator_input": {"name": "x", "type": "float", "choices": ["a"]}}]))
    assert any("choices" in x.message for x in d)


def test_min_max_only_numeric():
    d = diags(wf([{"operator_input": {"name": "x", "type": "bool", "min": 0}}]))
    assert any("min" in x.message for x in d)


def test_min_exceeds_max():
    d = diags(wf(
        [{"operator_input": {"name": "x", "type": "float", "min": 2.0, "max": 1.0}}]
    ))
    assert any("exceeds" in x.message for x in d)


def test_reserved_binding_name():
    d = diags(wf([{"operator_input": {"name": "not", "type": "float"}}]))
    assert any("binding name" in x.message for x in d)


def test_valid_operator_input():
    w = wf([{"operator_input": {"name": "target", "type": "float", "prompt": "t",
                                "min": 0.0, "max": 2.0}}])
    assert validate(w) is None


def test_measure_into_undeclared_stream():
    d = diags(wf([MEASURE_OD]))  # no streams declared
    assert any(x.category == "declaration" and "'OD'" in x.message for x in d)


def test_measure_requires_measurement_verb():
    w = wf(
        [{"measure": {"device": "pump_1", "verb": "dispense", "into": "OD",
                      "params": {"volume_ml": 1.0}}}],
        streams=["OD"],
    )
    d = diags(w)
    assert any(x.category == "block" and "measurement verb" in x.message for x in d)


def test_measure_into_non_string():
    w = Workflow(schema_version=1, blocks=[
        Measure(device="densitometer_1", verb="measure", into=5),
    ])
    assert any(x.category == "block" and "into" in x.message for x in diags(w))


def test_stat_over_undeclared_stream_in_condition():
    d = diags(wf(
        [{"branch": {"if": "count(ghost) > 0", "then": [MEASURE_OD]}}],
        streams=["OD"],
    ))
    assert any(x.category == "declaration" and "'ghost'" in x.message for x in d)


def test_stat_in_param_over_undeclared_stream():
    d = diags(wf([cmd("pump_1", "dispense", {"volume_ml": "mean(ghost)"})]))
    assert any(x.category == "declaration" and "'ghost'" in x.message for x in d)


def test_operator_input_unhashable_type_degrades():
    d = diags(wf([{"operator_input": {"name": "x", "type": ["float"]}}]))
    assert any(x.category == "block" and "float, int, enum, bool" in x.message for x in d)


def test_enum_choices_non_list_degrades():
    d = diags(wf([{"operator_input": {"name": "x", "type": "enum", "choices": 5}}]))
    assert any(x.category == "block" and "choices" in x.message for x in d)


def test_enum_choices_string_rejected():
    d = diags(wf([{"operator_input": {"name": "x", "type": "enum", "choices": "ab"}}]))
    assert any(x.category == "block" and "choices" in x.message for x in d)
