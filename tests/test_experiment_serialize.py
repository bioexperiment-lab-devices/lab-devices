import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import UnknownVerbError, WorkflowLoadError
from lab_devices.experiment.serialize import (
    block_from_dict,
    block_to_dict,
    workflow_from_dict,
    workflow_to_dict,
)


def test_command_with_timing():
    b = block_from_dict(
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 10}},
         "gap_after": "30s"}
    )
    assert isinstance(b, B.Command)
    assert b.device == "pump_1" and b.params == {"volume_ml": 10}
    assert b.gap_after == "30s"


def test_measure_and_loop_nesting():
    b = block_from_dict(
        {"loop": {"until": "last(OD) >= 1.0", "check": "after",
                  "body": [{"measure": {"device": "densitometer_1", "verb": "measure",
                                        "into": "OD"}}]}}
    )
    assert isinstance(b, B.Loop)
    assert b.check == "after"
    assert isinstance(b.body[0], B.Measure)
    assert b.body[0].into == "OD"


def test_branch_if_else_keyword_mapping():
    b = block_from_dict(
        {"branch": {"if": "last(OD) > 1.0",
                    "then": [{"command": {"device": "pump_2", "verb": "stop"}}],
                    "else": [{"command": {"device": "pump_1", "verb": "stop"}}]}}
    )
    assert isinstance(b, B.Branch)
    assert b.if_ == "last(OD) > 1.0"
    assert isinstance(b.else_[0], B.Command)


def test_unknown_verb_rejected_at_load():
    with pytest.raises(UnknownVerbError):
        block_from_dict({"command": {"device": "pump_1", "verb": "explode"}})


def test_multiple_type_keys_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"command": {"device": "pump_1", "verb": "stop"},
                         "measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}})


def test_loop_requires_exactly_one_of_count_or_until():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"loop": {"body": []}})
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"loop": {"count": 3, "until": "last(OD) > 1", "body": []}})


def test_malformed_params_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"command": {"device": "pump_1", "verb": "stop", "params": None}})
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"measure": {"device": "densitometer_1", "verb": "measure",
                                     "into": "OD", "params": "x"}})


def test_missing_required_fields_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"command": {"verb": "stop"}})  # missing device
    with pytest.raises(WorkflowLoadError):
        block_from_dict(  # missing into
            {"measure": {"device": "densitometer_1", "verb": "measure"}}
        )
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"wait": {}})  # missing duration


def test_non_dict_block_and_bad_children_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict("not a dict")
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"serial": {"children": "nope"}})
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"loop": {"until": "last(OD) > 1", "check": "sideways", "body": []}})


@pytest.mark.parametrize("payload", [
    {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 10}},
     "gap_after": "30s"},
    {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
    {"operator_input": {"name": "target", "type": "float", "prompt": "OD?",
                        "min": 0.0, "max": 2.0}},
    {"wait": {"duration": "5s"}},
    {"parallel": {"children": [
        {"command": {"device": "pump_1", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}},
         "start_offset": "1s"},
        {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}}]}},
    {"loop": {"until": "last(OD) >= 1.0", "check": "before",
              "body": [{"command": {"device": "pump_1", "verb": "stop"}}]}},
    {"loop": {"count": 3, "pace": "60s",
              "body": [{"measure": {"device": "densitometer_1", "verb": "measure",
                                    "into": "OD"}}]}},
    {"branch": {"if": "last(OD) > 1.0",
                "then": [{"command": {"device": "pump_2", "verb": "stop"}}],
                "else": [{"command": {"device": "pump_1", "verb": "stop"}}]}},
    {"group_ref": {"name": "prime_line"}, "label": "prime"},
    {"serial": {"children": [
        {"command": {"device": "valve_1", "verb": "home", "params": {"position": 0}}},
        {"wait": {"duration": "2s"}}]}, "label": "seq"},
    {"branch": {"if": "last(OD) > 1.0",
                "then": [{"command": {"device": "pump_1", "verb": "stop"}}]}},
    {"operator_input": {"name": "mode", "type": "enum", "choices": ["a", "b"]}},
])
def test_block_round_trip(payload):
    ast = block_from_dict(payload)
    assert block_to_dict(ast) == payload
    assert block_from_dict(block_to_dict(ast)) == ast


def test_non_string_device_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"command": {"device": 5, "verb": "stop"}})


def test_null_count_loop_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"loop": {"count": None, "body": []}})


def test_unknown_block_type_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"typo_key": {}})


def test_round_trip_preserves_retry_and_on_error():
    doc = {
        "schema_version": 1,
        "persistence": {"default": "in_memory", "format": "jsonl"},
        "defaults": {"retry": {"attempts": 2, "backoff": "5s"}},
        "streams": {"od_1": {"units": "AU"}},
        "blocks": [
            {
                "measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
                "label": "read OD",
                "retry": {"attempts": 3, "backoff": "2s"},
                "on_error": "continue",
            },
            {
                "command": {
                    "device": "pump_1", "verb": "dispense", "params": {"volume_ml": 0.5}
                },
                "retry": {"attempts": 2, "backoff": "1s", "allow_repeat": True},
            },
        ],
    }
    assert workflow_to_dict(workflow_from_dict(doc)) == doc


def test_retry_defaults_backoff_to_one_second():
    w = workflow_from_dict({
        "schema_version": 1,
        "streams": {"od_1": {}},
        "blocks": [{"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
                    "retry": {"attempts": 3}}],
    })
    assert w.blocks[0].retry.attempts == 3
    assert w.blocks[0].retry.backoff == "1s"
    assert w.blocks[0].retry.allow_repeat is False
    assert w.blocks[0].on_error == "fail"


def test_bad_on_error_value_rejected_at_load():
    with pytest.raises(WorkflowLoadError, match="on_error"):
        workflow_from_dict({
            "schema_version": 1,
            "blocks": [{"wait": {"duration": "1s"}, "on_error": "retry"}],
        })


def test_bad_retry_attempts_rejected_at_load():
    with pytest.raises(WorkflowLoadError, match="attempts"):
        workflow_from_dict({
            "schema_version": 1,
            "streams": {"od_1": {}},
            "blocks": [{"measure": {"device": "densitometer_1", "verb": "measure",
                                    "into": "od_1"}, "retry": {"attempts": 0}}],
        })


def test_defaults_on_error_rejected_at_load():
    with pytest.raises(WorkflowLoadError, match="on_error"):
        workflow_from_dict({
            "schema_version": 1,
            "defaults": {"on_error": "continue"},
            "blocks": [{"wait": {"duration": "1s"}}],
        })


def test_defaults_unknown_key_rejected_at_load():
    with pytest.raises(WorkflowLoadError, match="bogus"):
        workflow_from_dict({
            "schema_version": 1,
            "defaults": {"bogus": True},
            "blocks": [{"wait": {"duration": "1s"}}],
        })
