"""Expression-level static analysis: referenced names and type inference. See design §12."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from lab_devices.experiment.expr import (
    AllWindow,
    BinaryOp,
    BindingRef,
    Const,
    DurationWindow,
    Expr,
    StatCall,
    UnaryOp,
    Window,
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


ProvenWindows = Mapping[str, Window]
"""Streams proven non-empty, each mapped to the window the proof covers (design §5.2)."""


def windowed_reads(expr: Expr) -> tuple[StatCall, ...]:
    """Every value-reading stat call (i.e. not `count`), each with the window it slices.

    `count` is excluded for the same reason `ExprRefs` splits it out: it returns 0 on an
    empty window instead of raising, so it needs no non-emptiness proof at all.
    """
    found: list[StatCall] = []

    def walk(e: Expr) -> None:
        if isinstance(e, StatCall):
            if e.fn != "count":
                found.append(e)
        elif isinstance(e, UnaryOp):
            walk(e.operand)
        elif isinstance(e, BinaryOp):
            walk(e.left)
            walk(e.right)

    walk(expr)
    return tuple(found)


def proof_covers(proven: Window, read: Window) -> bool:
    """Does "window `proven` holds a sample" imply "window `read` holds a sample"?

    The sound lattice (design 2026-07-14 §5.2), read off `evaluate.py::_window_values`:

    - Any proof implies the stream holds >= 1 sample, and `_window_values` slices a
      `SampleWindow` as `samples[-n:]` with n >= 1 (the parser rejects n <= 0). A non-empty
      list always has a non-empty tail, so **every** proof discharges a whole-stream or
      sample-count read.
    - A `DurationWindow` is sliced by **timestamp cutoff** (`now - seconds`), so a stream
      can be non-empty while its last 5 minutes are empty. "The stream has a sample" is
      therefore no proof at all about a duration window.
    - A duration proof `last=D_guard` says a sample landed within D_guard of `now`. A read
      over `last=D_read` covers a strictly wider span iff `D_read >= D_guard`, and one
      `evaluate` call threads a single `now` — so the guard's sample is inside the read's
      window exactly then.
    """
    if not isinstance(read, DurationWindow):
        return True
    if not isinstance(proven, DurationWindow):
        return False
    return read.seconds >= proven.seconds


def conjoin_proofs(a: ProvenWindows, b: ProvenWindows) -> dict[str, Window]:
    """Both proofs hold (`and`): keep every stream, at the *strongest* proof for each."""
    joined = dict(a)
    for stream, window in b.items():
        held = joined.get(stream)
        joined[stream] = window if held is None else _stronger(held, window)
    return joined


def disjoin_proofs(a: ProvenWindows, b: ProvenWindows) -> dict[str, Window]:
    """Only one proof holds (`or`): keep streams proven by both, at the *weakest* proof."""
    return {stream: _weaker(a[stream], b[stream]) for stream in a.keys() & b.keys()}


def _stronger(a: Window, b: Window) -> Window:
    """The proof that discharges more reads: a narrower duration window beats a wider one,
    and any duration window beats a bare "the stream holds a sample"."""
    if isinstance(a, DurationWindow) and isinstance(b, DurationWindow):
        return a if a.seconds <= b.seconds else b
    return a if isinstance(a, DurationWindow) else b


def _weaker(a: Window, b: Window) -> Window:
    if isinstance(a, DurationWindow) and isinstance(b, DurationWindow):
        return a if a.seconds >= b.seconds else b
    return b if isinstance(a, DurationWindow) else a


def proven_nonempty(expr: Expr) -> dict[str, Window]:
    """Streams this expression proves non-empty whenever it evaluates True, each mapped to
    the window the proof covers (design 2026-07-14 §5.2).

    `count(S, W) > 0` proves that W holds a sample. Whether that discharges a given read is
    `proof_covers`'s question, not this one's.
    """
    if isinstance(expr, BinaryOp):
        if expr.op == "and":
            return conjoin_proofs(proven_nonempty(expr.left), proven_nonempty(expr.right))
        if expr.op == "or":
            return disjoin_proofs(proven_nonempty(expr.left), proven_nonempty(expr.right))
        return _proven_by_comparison(expr)
    return {}


def _count_call(e: Expr) -> StatCall | None:
    return e if isinstance(e, StatCall) and e.fn == "count" else None


def _int_const(e: Expr) -> int | None:
    if isinstance(e, Const) and isinstance(e.value, int) and not isinstance(e.value, bool):
        return e.value
    return None


def _proven_by_comparison(e: BinaryOp) -> dict[str, Window]:
    """`count(S, W) > k` (k>=0), `count(S, W) >= k` (k>=1), `count(S, W) != 0`, and mirrors."""
    call, bound, op = _count_call(e.left), _int_const(e.right), e.op
    if call is None or bound is None:  # try the mirrored form: k <op> count(S)
        call, bound = _count_call(e.right), _int_const(e.left)
        op = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}.get(e.op, e.op)
    if call is None or bound is None:
        return {}
    proves = (
        (op == ">" and bound >= 0)
        or (op == ">=" and bound >= 1)
        or (op == "!=" and bound == 0)
    )
    if not proves:
        return {}
    # A sample-count guard proves exactly what a whole-stream guard does — `samples[-n:]` is
    # non-empty iff the stream is — so it normalises away, keeping the lattice two-level.
    window = call.window if isinstance(call.window, DurationWindow) else AllWindow()
    return {call.stream: window}
