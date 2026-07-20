import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import UnknownVerbError, WorkflowLoadError
from lab_devices.experiment.serialize import (
    block_from_dict,
    block_to_dict,
    workflow_from_dict,
    workflow_to_dict,
)
from lab_devices.experiment.workflow import RoleDecl

ROLES = {
    "pump_1": RoleDecl(type="pump"),
    "pump_2": RoleDecl(type="pump"),
    "valve_1": RoleDecl(type="valve"),
    "densitometer_1": RoleDecl(type="densitometer"),
}
_ROLES_DOC = {name: {"type": r.type} for name, r in ROLES.items()}


def test_command_with_timing():
    b = block_from_dict(
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 10}},
         "gap_after": "30s"},
        ROLES,
    )
    assert isinstance(b, B.Command)
    assert b.device == "pump_1" and b.params == {"volume_ml": 10}
    assert b.gap_after == "30s"


def test_measure_and_loop_nesting():
    b = block_from_dict(
        {"loop": {"until": "last(OD) >= 1.0", "check": "after",
                  "body": [{"measure": {"device": "densitometer_1", "verb": "measure",
                                        "into": "OD"}}]}},
        ROLES,
    )
    assert isinstance(b, B.Loop)
    assert b.check == "after"
    assert isinstance(b.body[0], B.Measure)
    assert b.body[0].into == "OD"


def test_branch_if_else_keyword_mapping():
    b = block_from_dict(
        {"branch": {"if": "last(OD) > 1.0",
                    "then": [{"command": {"device": "pump_2", "verb": "stop"}}],
                    "else": [{"command": {"device": "pump_1", "verb": "stop"}}]}},
        ROLES,
    )
    assert isinstance(b, B.Branch)
    assert b.if_ == "last(OD) > 1.0"
    assert isinstance(b.else_[0], B.Command)


def test_unknown_verb_rejected_at_load():
    with pytest.raises(UnknownVerbError):
        block_from_dict({"command": {"device": "pump_1", "verb": "explode"}}, ROLES)


def test_multiple_type_keys_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"command": {"device": "pump_1", "verb": "stop"},
                         "measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
                        ROLES)


def test_loop_requires_exactly_one_of_count_or_until():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"loop": {"body": []}}, ROLES)
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"loop": {"count": 3, "until": "last(OD) > 1", "body": []}}, ROLES)


def test_malformed_params_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"command": {"device": "pump_1", "verb": "stop", "params": None}}, ROLES)
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"measure": {"device": "densitometer_1", "verb": "measure",
                                     "into": "OD", "params": "x"}}, ROLES)


def test_missing_required_fields_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"command": {"verb": "stop"}})  # missing device
    with pytest.raises(WorkflowLoadError):
        block_from_dict(  # missing into
            {"measure": {"device": "densitometer_1", "verb": "measure"}},
            ROLES,
        )
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"wait": {}})  # missing duration


def test_non_dict_block_and_bad_children_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict("not a dict")
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"serial": {"children": "nope"}}, ROLES)
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"loop": {"until": "last(OD) > 1", "check": "sideways", "body": []}}, ROLES)


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
    ast = block_from_dict(payload, ROLES)
    assert block_to_dict(ast) == payload
    assert block_from_dict(block_to_dict(ast), ROLES) == ast


def test_non_string_device_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"command": {"device": 5, "verb": "stop"}}, ROLES)


def test_null_count_loop_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"loop": {"count": None, "body": []}}, ROLES)


def test_unknown_block_type_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"typo_key": {}}, ROLES)


def test_round_trip_preserves_retry_and_on_error():
    doc = {
        "schema_version": 2,
        "persistence": {"default": "in_memory", "format": "jsonl"},
        "defaults": {"retry": {"attempts": 2, "backoff": "5s"}},
        "roles": _ROLES_DOC,
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
        "schema_version": 2,
        "roles": _ROLES_DOC,
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
            "schema_version": 2,
            "blocks": [{"wait": {"duration": "1s"}, "on_error": "retry"}],
        })


def test_bad_retry_attempts_rejected_at_load():
    with pytest.raises(WorkflowLoadError, match="attempts"):
        workflow_from_dict({
            "schema_version": 2,
            "streams": {"od_1": {}},
            "blocks": [{"measure": {"device": "densitometer_1", "verb": "measure",
                                    "into": "od_1"}, "retry": {"attempts": 0}}],
        })


def test_retry_nested_in_a_command_body_is_rejected_at_load():
    """`retry` is a sibling of `command`, not a member of it. Nested, it used to be silently
    dropped -- the author believes they have a retry policy and has none."""
    with pytest.raises(WorkflowLoadError, match="block-level key"):
        workflow_from_dict({
            "schema_version": 2,
            "blocks": [{"command": {"device": "pump_1", "verb": "dispense",
                                    "params": {"volume_ml": 0.5},
                                    "retry": {"attempts": 3, "allow_repeat": True}}}],
        })


def test_on_error_nested_in_a_measure_body_is_rejected_at_load():
    with pytest.raises(WorkflowLoadError, match="block-level key"):
        workflow_from_dict({
            "schema_version": 2,
            "streams": {"od_1": {}},
            "blocks": [{"measure": {"device": "densitometer_1", "verb": "measure",
                                    "into": "od_1", "on_error": "continue"}}],
        })


@pytest.mark.parametrize("body", [
    {"serial": {"children": [{"wait": {"duration": "1s"}}], "on_error": "continue"}},
    {"loop": {"body": [{"wait": {"duration": "1s"}}], "count": 1, "on_error": "continue"}},
    {"wait": {"duration": "1s", "on_error": "continue"}},
    {"branch": {"if": "true", "then": [{"wait": {"duration": "1s"}}], "on_error": "continue"}},
    {"parallel": {"children": [{"wait": {"duration": "1s"}}], "on_error": "continue"}},
    {"loop": {"body": [{"wait": {"duration": "1s"}}], "count": 1, "retry": {"attempts": 3}}},
    {"wait": {"duration": "1s", "retry": {"attempts": 3}}},
])
def test_a_misplaced_block_key_is_rejected_on_every_block_type(body):
    """`on_error` is legal on EVERY block type, so the silently-dropped-key trap is too:
    nested in a body it used to load and vanish, and the author believed they had a policy."""
    with pytest.raises(WorkflowLoadError, match="block-level key"):
        workflow_from_dict({"schema_version": 2, "blocks": [body]})


def test_defaults_on_error_rejected_at_load():
    with pytest.raises(WorkflowLoadError, match="on_error"):
        workflow_from_dict({
            "schema_version": 2,
            "defaults": {"on_error": "continue"},
            "blocks": [{"wait": {"duration": "1s"}}],
        })


def test_defaults_unknown_key_rejected_at_load():
    with pytest.raises(WorkflowLoadError, match="bogus"):
        workflow_from_dict({
            "schema_version": 2,
            "defaults": {"bogus": True},
            "blocks": [{"wait": {"duration": "1s"}}],
        })


def test_compute_roundtrip_expression():
    d = {"compute": {"into": "c", "value": "c * 0.5 + 1"}}
    b = block_from_dict(d)
    assert isinstance(b, B.Compute)
    assert b.into == "c" and b.value == "c * 0.5 + 1"
    assert block_to_dict(b) == d


def test_compute_roundtrip_literal_and_timing():
    d = {"compute": {"into": "seed", "value": 0}, "label": "seed c"}
    b = block_from_dict(d)
    assert isinstance(b, B.Compute)
    assert b.value == 0 and b.label == "seed c"
    assert block_to_dict(b) == d


def test_record_roundtrip():
    d = {"record": {"into": "r_series", "value": "r_1"}}
    b = block_from_dict(d)
    assert isinstance(b, B.Record)
    assert b.into == "r_series" and b.value == "r_1"
    assert block_to_dict(b) == d


def test_compute_requires_into_and_value():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"compute": {"value": "1"}}, ROLES)
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"compute": {"into": "c"}}, ROLES)


def test_record_value_bad_expression_rejected_at_load():
    from lab_devices.experiment.errors import ExpressionError
    with pytest.raises(ExpressionError):
        block_from_dict({"record": {"into": "r", "value": "1 +"}}, ROLES)


def test_compute_value_object_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"compute": {"into": "c", "value": {"nope": 1}}}, ROLES)


def test_workflow_roundtrip_with_compute_and_record():
    doc = {
        "schema_version": 2,
        "persistence": {"default": "in_memory", "format": "jsonl"},
        "streams": {"r_series": {"units": "per_hour"}},
        "blocks": [
            {"compute": {"into": "r_1", "value": "2 * 3"}},
            {"record": {"into": "r_series", "value": "r_1"}},
        ],
    }
    assert workflow_to_dict(workflow_from_dict(doc)) == doc


def test_abort_alarm_roundtrip():
    doc = {
        "schema_version": 2,
        "persistence": {"default": "in_memory", "format": "jsonl"},
        "streams": {"od_1": {}},
        "blocks": [
            {"abort": {"if": "count(od_1, last=1min) > 0 and last(od_1) > 2.0",
                       "message": "contaminated"}},
            {"alarm": {"if": "last(od_1) > 1.0", "message": "high od"}},
        ],
    }
    assert workflow_to_dict(workflow_from_dict(doc)) == doc


def test_abort_requires_if_and_message():
    with pytest.raises(WorkflowLoadError):
        workflow_from_dict({"schema_version": 2,
                            "blocks": [{"abort": {"message": "x"}}]})
    with pytest.raises(WorkflowLoadError):
        workflow_from_dict({"schema_version": 2,
                            "blocks": [{"abort": {"if": "true"}}]})


def test_alarm_requires_if_and_message():
    with pytest.raises(WorkflowLoadError):
        workflow_from_dict({"schema_version": 2,
                            "blocks": [{"alarm": {"message": "x"}}]})
    with pytest.raises(WorkflowLoadError):
        workflow_from_dict({"schema_version": 2,
                            "blocks": [{"alarm": {"if": "true"}}]})
