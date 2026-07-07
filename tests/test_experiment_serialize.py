import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import UnknownVerbError, WorkflowLoadError
from lab_devices.experiment.serialize import block_from_dict


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
