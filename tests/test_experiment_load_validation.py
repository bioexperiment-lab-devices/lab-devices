import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import ExpressionError, ValidationError, WorkflowLoadError
from lab_devices.experiment.serialize import block_from_dict, workflow_from_dict
from lab_devices.experiment.validate import validate
from lab_devices.experiment.workflow import RoleDecl

ROLES = {
    "pump_1": RoleDecl(type="pump"),
    "pump_2": RoleDecl(type="pump"),
    "densitometer_1": RoleDecl(type="densitometer"),
}


def test_bad_param_expression_fails_at_load():
    with pytest.raises(ExpressionError, match="param 'volume_ml'"):
        block_from_dict({"command": {"device": "pump_1", "verb": "dispense",
                                     "params": {"volume_ml": "2.0 * ("}}}, ROLES)


def test_deeply_nested_param_expression_fails_at_load():
    # ExpressionError is a WorkflowLoadError subclass; the load path only promises the base.
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"command": {"device": "pump_1", "verb": "dispense",
                                     "params": {"v": "(" * 300 + "1" + ")" * 300}}}, ROLES)


def test_bad_measure_param_fails_at_load():
    with pytest.raises(ExpressionError):
        block_from_dict({"measure": {"device": "densitometer_1", "verb": "measure",
                                     "into": "OD", "params": {"x": "1 +"}}}, ROLES)


def test_bad_branch_condition_fails_at_load():
    with pytest.raises(ExpressionError, match="branch if"):
        block_from_dict({"branch": {"if": "last(OD >", "then": []}})


def test_bad_loop_until_fails_at_load():
    with pytest.raises(ExpressionError, match="loop until"):
        block_from_dict({"loop": {"until": "mean(", "body": []}})


def test_non_string_conditions_rejected():
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"branch": {"if": 5, "then": []}})
    with pytest.raises(WorkflowLoadError):
        block_from_dict({"loop": {"until": True, "body": []}})


def test_bad_durations_fail_validation():
    """Durations are `number<s>` expressions now (design 2026-07-21 §6): a malformed literal or
    a bare unitless number is a validate-time diagnostic, not a load error."""
    def rejects(block: dict) -> None:
        doc = {"schema_version": 3, "roles": {"pump_1": {"type": "pump"}},
               "streams": {}, "blocks": [block]}
        with pytest.raises(ValidationError):
            validate(workflow_from_dict(doc))

    stop = {"device": "pump_1", "verb": "stop"}
    rejects({"command": stop, "gap_after": "30 sec"})       # bad grammar
    rejects({"wait": {"duration": "5"}})                    # unitless, needs <s>
    rejects({"wait": {"duration": "1 minute"}})             # bad grammar
    rejects({"loop": {"count": 3, "pace": "5", "body": [{"wait": {"duration": "1s"}}]}})


def test_enum_like_string_params_still_load():
    b = block_from_dict({"command": {"device": "pump_2", "verb": "rotate",
                                     "params": {"direction": "forward",
                                                "speed_ml_min": 2.0}}}, ROLES)
    assert isinstance(b, B.Command)
    assert b.params["direction"] == "forward"


def test_feedback_expression_param_loads_verbatim():
    text = "2.0 * (target_OD - mean(OD, last=100))"
    b = block_from_dict({"command": {"device": "pump_1", "verb": "dispense",
                                     "params": {"volume_ml": text}}}, ROLES)
    assert isinstance(b, B.Command)
    assert b.params["volume_ml"] == text


def test_valid_durations_load_verbatim():
    b = block_from_dict({"command": {"device": "pump_1", "verb": "stop"},
                         "gap_after": "30s"}, ROLES)
    assert b.gap_after == "30s"


def test_bad_expression_inside_group_body_fails_at_load():
    doc = {"schema_version": 3,
           "groups": {"g": {"body": [{"branch": {"if": "((", "then": []}}]}},
           "blocks": []}
    with pytest.raises(ExpressionError):
        workflow_from_dict(doc)
