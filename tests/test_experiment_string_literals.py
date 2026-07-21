"""Single-quoted string literals and string equality make an enum operator input branchable
(engine-limitation #5). See design 2026-07-21 §6, Engine A plan Task 5."""

from __future__ import annotations

import pytest

from lab_devices.experiment.analyze import infer_type
from lab_devices.experiment.errors import EvaluationError
from lab_devices.experiment.evaluate import evaluate
from lab_devices.experiment.expr import BinaryOp, Const, parse_expression
from lab_devices.experiment.state import RunState
from lab_devices.experiment.validate import validate
from tests.experiment_validate_helpers import wf


def test_single_quoted_string_literal_parses() -> None:
    e = parse_expression("mode == 'chemostat'")
    assert isinstance(e, BinaryOp) and e.op == "=="
    assert isinstance(e.right, Const) and e.right.value == "chemostat"


def test_string_literal_infers_as_string() -> None:
    assert infer_type(parse_expression("'x'"), {}).type.base == "string"


def test_string_equality_evaluates() -> None:
    st = RunState()
    st.bind("mode", "chemostat")
    assert evaluate(parse_expression("mode == 'chemostat'"), st, 0.0) is True
    assert evaluate(parse_expression("mode == 'turbidostat'"), st, 0.0) is False
    assert evaluate(parse_expression("mode != 'turbidostat'"), st, 0.0) is True


def test_string_still_rejected_in_arithmetic_at_runtime() -> None:
    st = RunState()
    st.bind("mode", "chemostat")
    with pytest.raises(EvaluationError):
        evaluate(parse_expression("mode + 1"), st, 0.0)


def test_comparing_string_with_number_raises_at_runtime() -> None:
    with pytest.raises(EvaluationError):
        evaluate(parse_expression("'a' == 1"), RunState(), 0.0)


def test_enum_input_is_branchable() -> None:
    # The headline of limitation #5: an enum choice can now drive control flow.
    validate(wf([
        {"operator_input": {"name": "mode", "type": "enum",
                            "choices": ["chemostat", "turbidostat"]}},
        {"branch": {"if": "mode == 'chemostat'", "then": []}},
    ]))  # must not raise


def test_unterminated_string_is_a_parse_error() -> None:
    from lab_devices.experiment.errors import ExpressionError
    with pytest.raises(ExpressionError):
        parse_expression("mode == 'chemostat")
