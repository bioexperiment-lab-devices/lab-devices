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
from lab_devices.experiment.units import UNITLESS, Unit, unit_div, unit_mul, unit_str

# One scalar type vocabulary for the whole DSL (design 2026-07-21 §3). `int <: number`;
# `bool`/`string` are invariant; `unknown` is the transient inference state.
Base = Literal["int", "number", "bool", "string", "unknown"]
Type = Base  # legacy alias for the base name

_ARITH_OPS = frozenset({"+", "-", "*", "/"})
_ORDER_OPS = frozenset({"<", "<=", ">", ">="})
_NUMERIC: frozenset[str] = frozenset({"int", "number"})
_EMPTY_UNITS: dict[str, Unit] = {}


@dataclass(frozen=True)
class ScalarType:
    """A scalar's base and, for numerics, its opaque unit (design 2026-07-21 §3, §5).
    `bool`/`string`/`unknown` carry no unit (it stays `UNITLESS`)."""

    base: Base
    unit: Unit = UNITLESS


UNKNOWN = ScalarType("unknown")
BindingType = ScalarType  # a binding's inferred type
ExprType = ScalarType  # an expression's inferred type


def assignable(got: Base, expected: Base) -> bool:
    """Base subtyping only (design §3.1): `int <: number`, every other base invariant,
    `unknown` leniently assignable in either direction. Unit compatibility is a separate
    check the caller applies (`validate._check_expr_type`)."""
    if got == "unknown" or expected == "unknown":
        return True
    if got == expected:
        return True
    return got == "int" and expected == "number"


def _join_base(a: Base, b: Base) -> Base:
    if a == b:
        return a
    if a in _NUMERIC and b in _NUMERIC:  # {int, number} -> number
        return "number"
    return "unknown"


def join_types(a: ScalarType, b: ScalarType) -> ScalarType:
    """Least upper bound of two writers of one binding (design §4.1). Bases: int/number widen
    to number, else same-or-unknown. Units: equal keeps it; unitless widens to the dimensioned
    side (a seed `0` then an `AU` value is one `AU` accumulator); two *different* dimensioned
    units conflict to `unknown`."""
    base = _join_base(a.base, b.base)
    if base == "unknown":
        return UNKNOWN
    if a.unit == b.unit:
        unit = a.unit
    elif a.unit == UNITLESS:
        unit = b.unit
    elif b.unit == UNITLESS:
        unit = a.unit
    else:
        return UNKNOWN  # two dimensioned units disagree
    return ScalarType(base, unit)


def _fmt(t: ScalarType) -> str:
    """Render a type for a diagnostic: `number<AU/s>`, `int`, `bool`."""
    if t.base in _NUMERIC and t.unit != UNITLESS:
        return f"{t.base}<{unit_str(t.unit)}>"
    return t.base


def _describe(e: Expr, t: ScalarType) -> str:
    """Render an operand's type, naming a bare binding so the author knows which is mistyped
    (e.g. `mode * 2` -> "string (binding 'mode')")."""
    shown = _fmt(t)
    if isinstance(e, BindingRef):
        return f"{shown} (binding {e.name!r})"
    return shown


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


def infer_type(
    expr: Expr,
    binding_types: Mapping[str, BindingType],
    stream_units: Mapping[str, Unit] = _EMPTY_UNITS,
) -> TypeReport:
    """Bottom-up type inference over the scalar lattice with opaque units (design §3, §5).

    A `string` binding flows as `string` (a problem only in a non-string position). Within an
    operator a **unitless operand adapts** to its sibling's unit (§3.2); two differently
    dimensioned operands are a problem. `×`/`÷` combine units. `unknown` operands never raise —
    that leniency is the fail-safe rule (§6); slot-level strictness lives in `validate`.
    """
    problems: list[str] = []

    def expect_bool(e: Expr, ctx: str) -> None:
        got = infer(e)
        if not assignable(got.base, "bool"):
            problems.append(f"{ctx} requires a bool operand, got {_describe(e, got)}")

    def numeric(e: Expr, ctx: str) -> ScalarType:
        got = infer(e)
        if got.base not in _NUMERIC and got.base != "unknown":
            problems.append(f"{ctx} requires a number operand, got {_describe(e, got)}")
            return ScalarType("number")
        return got

    def combine_add(lt: ScalarType, rt: ScalarType, e: BinaryOp, ctx: str) -> Unit:
        """Unit rule for +/- and comparison: equal, or one side unitless (adapts §3.2)."""
        if lt.unit == rt.unit:
            return lt.unit
        if lt.unit == UNITLESS:
            return rt.unit
        if rt.unit == UNITLESS:
            return lt.unit
        problems.append(
            f"{ctx} needs matching units, got "
            f"{_describe(e.left, lt)} and {_describe(e.right, rt)}"
        )
        return UNITLESS

    def equality(e: BinaryOp) -> ScalarType:
        left, right = infer(e.left), infer(e.right)
        if "unknown" not in (left.base, right.base):
            if left.base in _NUMERIC and right.base in _NUMERIC:
                combine_add(left, right, e, f"operator {e.op!r}")
            elif left.base != right.base:
                problems.append(
                    f"operator {e.op!r} cannot compare "
                    f"{_describe(e.left, left)} with {_describe(e.right, right)}"
                )
        return ScalarType("bool")

    def infer(e: Expr) -> ScalarType:
        if isinstance(e, Const):
            if isinstance(e.value, bool):
                return ScalarType("bool")
            if isinstance(e.value, str):
                return ScalarType("string")
            return ScalarType("int" if isinstance(e.value, int) else "number")
        if isinstance(e, BindingRef):
            return binding_types.get(e.name, UNKNOWN)
        if isinstance(e, StatCall):
            if e.fn == "count":
                return ScalarType("int")
            return ScalarType("number", stream_units.get(e.stream, UNITLESS))
        if isinstance(e, UnaryOp):
            if e.op == "not":
                expect_bool(e.operand, "'not'")
                return ScalarType("bool")
            return numeric(e.operand, "unary '-'")  # preserves base and unit
        if e.op in ("and", "or"):
            expect_bool(e.left, f"{e.op!r}")
            expect_bool(e.right, f"{e.op!r}")
            return ScalarType("bool")
        if e.op in _ARITH_OPS:
            lt = numeric(e.left, f"operator {e.op!r}")
            rt = numeric(e.right, f"operator {e.op!r}")
            base: Base = (
                "int" if e.op != "/" and lt.base == "int" and rt.base == "int" else "number"
            )
            if e.op == "*":
                unit = unit_mul(lt.unit, rt.unit)
            elif e.op == "/":
                unit = unit_div(lt.unit, rt.unit)
            else:  # + or -
                unit = combine_add(lt, rt, e, f"operator {e.op!r}")
            return ScalarType(base, unit)
        if e.op in _ORDER_OPS:
            lt = numeric(e.left, f"operator {e.op!r}")
            rt = numeric(e.right, f"operator {e.op!r}")
            combine_add(lt, rt, e, f"operator {e.op!r}")
            return ScalarType("bool")
        return equality(e)  # == / !=

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
