import pytest

import lab_devices.experiment as exp
from lab_devices.experiment.errors import (
    ExperimentError,
    UnknownVerbError,
    WorkflowLoadError,
)


def test_error_hierarchy():
    assert issubclass(WorkflowLoadError, ExperimentError)
    assert issubclass(UnknownVerbError, WorkflowLoadError)
    err = UnknownVerbError("nope")
    assert isinstance(err, ExperimentError)
    assert str(err) == "nope"


def test_expression_engine_end_to_end():
    state = exp.RunState()
    state.bind("target_OD", 0.8)
    state.record("OD", 0.0, 0.5)
    state.record("OD", 10.0, 0.6)
    volume = exp.resolve("2.0 * (target_OD - mean(OD, last=100))", state, now=10.0)
    assert volume == pytest.approx(0.5)
    assert exp.resolve("mean(OD, last=5min) >= target_OD", state, now=10.0) is False
    assert exp.resolve("count(OD) >= 2 and last(OD) > 0.55", state, now=10.0) is True


def test_expression_engine_error_types_exported():
    with pytest.raises(exp.ExpressionError):
        exp.parse_expression("2 *")
    with pytest.raises(exp.EvaluationError):
        exp.evaluate(exp.parse_expression("nope + 1"), exp.RunState(), now=0.0)
