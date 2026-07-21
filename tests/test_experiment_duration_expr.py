"""Duration literals are `number<s>` expression values (design 2026-07-21 §6, Engine C Task 1)."""

from __future__ import annotations

from lab_devices.experiment.analyze import ScalarType, infer_type
from lab_devices.experiment.evaluate import evaluate
from lab_devices.experiment.expr import DurationConst, StatCall, parse_expression
from lab_devices.experiment.state import RunState
from lab_devices.experiment.units import parse_unit

_SECONDS = parse_unit("s")


def test_duration_literal_parses_to_a_duration_const() -> None:
    e = parse_expression("5min")
    assert isinstance(e, DurationConst) and e.seconds == 300.0


def test_duration_literal_infers_as_number_in_seconds() -> None:
    assert infer_type(parse_expression("30s"), {}).type == ScalarType("number", _SECONDS)
    assert infer_type(parse_expression("1.5h"), {}).type == ScalarType("number", _SECONDS)


def test_duration_arithmetic_keeps_the_seconds_unit() -> None:
    binds = {"cycle_min": ScalarType("number")}
    assert infer_type(parse_expression("cycle_min * 1min"), binds).type.unit == _SECONDS
    # A bare unitless number is NOT a duration — Task 3's slot check rejects it.
    assert infer_type(parse_expression("cycle_min"), binds).type.unit == ()


def test_duration_literal_evaluates_to_seconds() -> None:
    st = RunState()
    assert evaluate(parse_expression("5min"), st, 0.0) == 300.0
    assert evaluate(parse_expression("2 * 30s"), st, 0.0) == 60.0
    assert evaluate(parse_expression("250ms"), st, 0.0) == 0.25


def test_duration_in_a_stat_window_still_parses() -> None:
    # The window path consumes the DURATION token directly, not via `_atom`, so it is
    # unaffected: `last=5min` remains a window, not a value.
    e = parse_expression("count(s, last=5min) > 0")
    # left side is the count stat call
    assert isinstance(e.left, StatCall) and e.left.fn == "count"
