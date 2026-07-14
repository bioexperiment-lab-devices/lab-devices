"""Expression-level static analysis: referenced names and type inference. See design §12."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from lab_devices.experiment.expr import (
    BinaryOp,
    BindingRef,
    Const,
    Expr,
    StatCall,
    UnaryOp,
)

BindingType = Literal["number", "boolean", "string", "unknown"]
ExprType = Literal["number", "boolean", "unknown"]

_ARITH_OPS = frozenset({"+", "-", "*", "/"})
_ORDER_OPS = frozenset({"<", "<=", ">", ">="})


@dataclass(frozen=True)
class ExprRefs:
    """Names an expression consumes, split by how they are consumed (design §12)."""

    bindings: frozenset[str]
    streams_windowed: frozenset[str]  # via last/mean/min/max: need a definite prior writer
    streams_counted: frozenset[str]  # via count only: need declaration only


def references(expr: Expr) -> ExprRefs:
    """Enumerate every binding and stream an expression references."""
    bindings: set[str] = set()
    windowed: set[str] = set()
    counted: set[str] = set()

    def walk(e: Expr) -> None:
        if isinstance(e, BindingRef):
            bindings.add(e.name)
        elif isinstance(e, StatCall):
            (counted if e.fn == "count" else windowed).add(e.stream)
        elif isinstance(e, UnaryOp):
            walk(e.operand)
        elif isinstance(e, BinaryOp):
            walk(e.left)
            walk(e.right)

    walk(expr)
    return ExprRefs(frozenset(bindings), frozenset(windowed), frozenset(counted))


@dataclass(frozen=True)
class TypeReport:
    """Inferred expression type plus every type problem found (design §12)."""

    type: ExprType
    problems: tuple[str, ...]


def infer_type(expr: Expr, binding_types: Mapping[str, BindingType]) -> TypeReport:
    """Lenient bottom-up type inference; 'unknown' never produces a problem —
    the runtime evaluator (fail-safe rule, design §6) is the backstop."""
    problems: list[str] = []

    def expect(e: Expr, expected: ExprType, ctx: str) -> None:
        got = infer(e)
        if got not in (expected, "unknown"):
            problems.append(f"{ctx} requires a {expected} operand, got {got}")

    def infer(e: Expr) -> ExprType:
        if isinstance(e, Const):
            return "boolean" if isinstance(e.value, bool) else "number"
        if isinstance(e, BindingRef):
            bound = binding_types.get(e.name, "unknown")
            if bound == "string":
                problems.append(
                    f"binding {e.name!r} holds a string (enum operator input); "
                    "expressions evaluate numbers and booleans"
                )
                return "unknown"
            if bound == "number" or bound == "boolean":
                return bound
            return "unknown"
        if isinstance(e, StatCall):
            return "number"
        if isinstance(e, UnaryOp):
            if e.op == "not":
                expect(e.operand, "boolean", "'not'")
                return "boolean"
            expect(e.operand, "number", "unary '-'")
            return "number"
        if e.op in ("and", "or"):
            expect(e.left, "boolean", f"{e.op!r}")
            expect(e.right, "boolean", f"{e.op!r}")
            return "boolean"
        if e.op in _ARITH_OPS:
            expect(e.left, "number", f"operator {e.op!r}")
            expect(e.right, "number", f"operator {e.op!r}")
            return "number"
        if e.op in _ORDER_OPS:
            expect(e.left, "number", f"operator {e.op!r}")
            expect(e.right, "number", f"operator {e.op!r}")
            return "boolean"
        left, right = infer(e.left), infer(e.right)  # == / !=
        if "unknown" not in (left, right) and left != right:
            problems.append(f"operator {e.op!r} cannot compare a boolean with a number")
        return "boolean"

    top = infer(expr)
    return TypeReport(top, tuple(problems))


def proven_nonempty(expr: Expr) -> frozenset[str]:
    """Streams this expression proves non-empty whenever it evaluates True.

    A windowed stat only raises on a *truly empty* window (evaluate.py `_stat`); a short
    window is fine. So `count(S) > 0` is enough to make any windowed stat on S safe
    (design 2026-07-14 §5.2).
    """
    if isinstance(expr, BinaryOp):
        if expr.op == "and":
            return proven_nonempty(expr.left) | proven_nonempty(expr.right)
        if expr.op == "or":
            return proven_nonempty(expr.left) & proven_nonempty(expr.right)
        return _proven_by_comparison(expr)
    return frozenset()


def _count_stream(e: Expr) -> str | None:
    return e.stream if isinstance(e, StatCall) and e.fn == "count" else None


def _int_const(e: Expr) -> int | None:
    if isinstance(e, Const) and isinstance(e.value, int) and not isinstance(e.value, bool):
        return e.value
    return None


def _proven_by_comparison(e: BinaryOp) -> frozenset[str]:
    """`count(S) > k` (k>=0), `count(S) >= k` (k>=1), `count(S) != 0`, and mirrors."""
    stream, bound, op = _count_stream(e.left), _int_const(e.right), e.op
    if stream is None or bound is None:  # try the mirrored form: k <op> count(S)
        stream, bound = _count_stream(e.right), _int_const(e.left)
        op = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}.get(e.op, e.op)
    if stream is None or bound is None:
        return frozenset()
    proves = (
        (op == ">" and bound >= 0)
        or (op == ">=" and bound >= 1)
        or (op == "!=" and bound == 0)
    )
    return frozenset({stream}) if proves else frozenset()
