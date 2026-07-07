import pytest

from lab_devices.experiment.durations import parse_duration
from lab_devices.experiment.errors import (
    EvaluationError,
    ExperimentError,
    ExpressionError,
    WorkflowLoadError,
)


def test_new_error_taxonomy():
    assert issubclass(ExpressionError, WorkflowLoadError)
    assert issubclass(EvaluationError, ExperimentError)
    assert not issubclass(EvaluationError, WorkflowLoadError)


def test_basic_units():
    assert parse_duration("30s") == 30.0
    assert parse_duration("5min") == 300.0
    assert parse_duration("1h") == 3600.0
    assert parse_duration("250ms") == 0.25


def test_fractional_values():
    assert parse_duration("1.5min") == 90.0
    assert parse_duration("0.5s") == 0.5


def test_surrounding_whitespace_is_tolerated():
    assert parse_duration(" 30s ") == 30.0


def test_result_is_float():
    assert isinstance(parse_duration("30s"), float)


@pytest.mark.parametrize(
    "bad", ["", "30", "s", "5 min", "5m", "-30s", "30sec", "min5", "1h30min", "5MIN"]
)
def test_invalid_durations_raise_value_error(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)
