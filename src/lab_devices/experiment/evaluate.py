"""Expression evaluator with fail-safe missing-data semantics. See design §6-8."""

from __future__ import annotations

import math
from bisect import bisect_left
from collections.abc import Sequence

from lab_devices.experiment.blocks import ValueExpr
from lab_devices.experiment.errors import EvaluationError
from lab_devices.experiment.expr import (
    BinaryOp,
    BindingRef,
    Const,
    DurationWindow,
    Expr,
    SampleWindow,
    StatCall,
    UnaryOp,
    parse_expression,
)
from lab_devices.experiment.state import RunState, Sample

Value = int | float | bool

_ARITH_OPS = frozenset({"+", "-", "*", "/"})
_ORDER_OPS = frozenset({"<", "<=", ">", ">="})


def evaluate(expr: Expr, state: RunState, now: float) -> Value:
    """Evaluate a parsed expression; raises EvaluationError if no value can be produced."""
    if isinstance(expr, Const):
        return expr.value
    if isinstance(expr, BindingRef):
        return _binding(expr, state)
    if isinstance(expr, StatCall):
        return _stat(expr, state, now)
    if isinstance(expr, UnaryOp):
        return _unary(expr, state, now)
    return _binary(expr, state, now)


def resolve(value: ValueExpr, state: RunState, now: float) -> Value:
    """Resolve a block scalar slot: literals pass through, strings parse and evaluate."""
    if isinstance(value, str):
        return evaluate(parse_expression(value), state, now)
    return value


def _binding(ref: BindingRef, state: RunState) -> Value:
    if ref.name not in state.bindings:
        raise EvaluationError(f"unbound binding {ref.name!r}")
    bound = state.bindings[ref.name]
    if isinstance(bound, str):
        raise EvaluationError(
            f"binding {ref.name!r} holds a string; expressions evaluate numbers and booleans"
        )
    if isinstance(bound, float) and not math.isfinite(bound):
        raise EvaluationError(f"binding {ref.name!r} holds a non-finite value")
    return bound


def _number(value: Value, ctx: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"{ctx} requires a number, got {value!r}")
    if isinstance(value, float) and not math.isfinite(value):
        raise EvaluationError(f"{ctx} got a non-finite number {value!r}")
    return value


def _boolean(value: Value, ctx: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationError(f"{ctx} requires a boolean, got {value!r}")
    return value


def _unary(expr: UnaryOp, state: RunState, now: float) -> Value:
    if expr.op == "not":
        return not _boolean(evaluate(expr.operand, state, now), "'not'")
    return -_number(evaluate(expr.operand, state, now), "unary '-'")


def _binary(expr: BinaryOp, state: RunState, now: float) -> Value:
    if expr.op == "and":
        # Short-circuit enables guard conditions: count(S) > 0 and mean(S) > x (§6).
        if not _boolean(evaluate(expr.left, state, now), "'and'"):
            return False
        return _boolean(evaluate(expr.right, state, now), "'and'")
    if expr.op == "or":
        if _boolean(evaluate(expr.left, state, now), "'or'"):
            return True
        return _boolean(evaluate(expr.right, state, now), "'or'")
    left = evaluate(expr.left, state, now)
    right = evaluate(expr.right, state, now)
    ctx = f"operator {expr.op!r}"
    if expr.op in _ARITH_OPS:
        return _arith(expr.op, _number(left, ctx), _number(right, ctx))
    if expr.op in _ORDER_OPS:
        return _compare(expr.op, _number(left, ctx), _number(right, ctx))
    if isinstance(left, bool) != isinstance(right, bool):
        raise EvaluationError(f"{ctx} cannot compare a boolean with a number")
    return (left == right) if expr.op == "==" else (left != right)


def _arith(op: str, left: int | float, right: int | float) -> int | float:
    try:
        if op == "+":
            result = left + right
        elif op == "-":
            result = left - right
        elif op == "*":
            result = left * right
        else:
            if right == 0:
                raise EvaluationError("division by zero")
            result = left / right
    except OverflowError as exc:
        raise EvaluationError(f"operator {op!r}: arithmetic overflow") from exc
    if isinstance(result, float) and not math.isfinite(result):
        raise EvaluationError(f"operator {op!r}: arithmetic overflow")
    return result


def _compare(op: str, left: int | float, right: int | float) -> bool:
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left >= right


def _stat(call: StatCall, state: RunState, now: float) -> Value:
    values = _window_values(call, state, now)
    if call.fn == "count":
        return len(values)
    if not values:
        raise EvaluationError(f"{call.fn}({call.stream}): empty stream window")
    if call.fn == "last":
        result = values[-1]
    elif call.fn == "mean":
        try:
            result = sum(values) / len(values)
        except OverflowError as exc:
            raise EvaluationError(f"mean({call.stream}): arithmetic overflow") from exc
    elif call.fn == "min":
        result = min(values)
    else:
        result = max(values)
    if not math.isfinite(result):
        raise EvaluationError(f"{call.fn}({call.stream}): non-finite result")
    return result


def _window_values(call: StatCall, state: RunState, now: float) -> list[float]:
    stream = state.streams.get(call.stream)
    if stream is None:
        raise EvaluationError(f"unknown stream {call.stream!r}")
    samples: Sequence[Sample] = stream.samples
    if isinstance(call.window, SampleWindow):
        samples = samples[-call.window.n:]
    elif isinstance(call.window, DurationWindow):
        cutoff = now - call.window.seconds  # inclusive: sample at the cutoff counts
        start = bisect_left(samples, cutoff, key=lambda s: s.timestamp)
        samples = samples[start:]
    return [s.value for s in samples]
