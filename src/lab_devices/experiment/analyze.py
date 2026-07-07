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
