import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import ExpressionError, WorkflowLoadError
from lab_devices.experiment.serialize import block_from_dict, workflow_from_dict


def test_bad_param_expression_fails_at_load():
    with pytest.raises(ExpressionError, match="param 'volume_ml'"):
        block_from_dict({"command": {"device": "pump_1", "verb": "dispense",
                                     "params": {"volume_ml": "2.0 * ("}}})


def test_bad_measure_param_fails_at_load():
    with pytest.raises(ExpressionError):
        block_from_dict({"measure": {"device": "densitometer_1", "verb": "measure",
                                     "into": "OD", "params": {"x": "1 +"}}})


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


def test_bad_durations_fail_at_load():
    stop = {"device": "pump_1", "verb": "stop"}
    with pytest.raises(WorkflowLoadError, match="gap_after"):
        block_from_dict({"command": stop, "gap_after": "30 sec"})
    with pytest.raises(WorkflowLoadError, match="start_offset"):
        block_from_dict({"command": stop, "start_offset": "later"})
    with pytest.raises(WorkflowLoadError, match="wait duration"):
        block_from_dict({"wait": {"duration": "5"}})
    with pytest.raises(WorkflowLoadError, match="loop pace"):
        block_from_dict({"loop": {"count": 3, "pace": "1 minute", "body": []}})


def test_enum_like_string_params_still_load():
    b = block_from_dict({"command": {"device": "pump_2", "verb": "rotate",
                                     "params": {"direction": "forward",
                                                "speed_ml_min": 2.0}}})
    assert isinstance(b, B.Command)
    assert b.params["direction"] == "forward"


def test_feedback_expression_param_loads_verbatim():
    text = "2.0 * (target_OD - mean(OD, last=100))"
    b = block_from_dict({"command": {"device": "pump_1", "verb": "dispense",
                                     "params": {"volume_ml": text}}})
    assert isinstance(b, B.Command)
    assert b.params["volume_ml"] == text


def test_valid_durations_load_verbatim():
    b = block_from_dict({"command": {"device": "pump_1", "verb": "stop"},
                         "gap_after": "30s"})
    assert b.gap_after == "30s"


def test_bad_expression_inside_group_body_fails_at_load():
    doc = {"schema_version": 1,
           "groups": {"g": {"body": [{"branch": {"if": "((", "then": []}}]}},
           "blocks": []}
    with pytest.raises(ExpressionError):
        workflow_from_dict(doc)
