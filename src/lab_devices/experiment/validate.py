"""Static workflow validator: registry, affinity, mode lifetimes, data-flow. See design §12."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from lab_devices.experiment import blocks as B
from lab_devices.experiment._legacy_ids import legacy_device_type
from lab_devices.experiment.analyze import (
    BindingType,
    ExprType,
    ProvenWindows,
    conjoin_proofs,
    infer_type,
    proof_covers,
    proven_nonempty,
    references,
    windowed_reads,
)
from lab_devices.experiment.errors import (
    Diagnostic,
    ExpressionError,
    UnknownVerbError,
    ValidationError,
    WorkflowLoadError,
)
from lab_devices.experiment.expand import expand_workflow
from lab_devices.experiment.expr import (
    AllWindow,
    BinaryOp,
    DurationWindow,
    Expr,
    SampleWindow,
    Window,
    parse_expression,
)
from lab_devices.experiment.registry import ParamSpec, lookup, mode_action
from lab_devices.experiment.serialize import load_workflow
from lab_devices.experiment.workflow import Workflow


def _iter_blocks(blocks: list[B.Block], prefix: str) -> Iterator[tuple[str, B.Block]]:
    """Depth-first (path, block) pairs; group refs are yielded, not expanded."""
    for i, b in enumerate(blocks):
        path = f"{prefix}[{i}]"
        yield path, b
        if isinstance(b, (B.Serial, B.Parallel)):
            yield from _iter_blocks(b.children, f"{path}.children")
        elif isinstance(b, B.Loop):
            yield from _iter_blocks(b.body, f"{path}.body")
        elif isinstance(b, B.Branch):
            yield from _iter_blocks(b.then, f"{path}.then")
            if b.else_ is not None:
                yield from _iter_blocks(b.else_, f"{path}.else")
        elif isinstance(b, B.ForEach):
            yield from _iter_blocks(b.body, f"{path}.body")


def _iter_all_blocks(w: Workflow) -> Iterator[tuple[str, B.Block]]:
    yield from _iter_blocks(w.blocks, "blocks")
    for name, group in w.groups.items():
        yield from _iter_blocks(group.body, f"groups[{name!r}].body")


def _check_groups(w: Workflow, out: list[Diagnostic]) -> bool:
    """Unknown group refs and self/mutual recursion (design §12); True iff expandable."""
    ok = True
    for path, b in _iter_all_blocks(w):
        if isinstance(b, B.GroupRef):
            if not isinstance(b.name, str):
                out.append(Diagnostic(
                    "group", path, f"group_ref name must be a string, got {b.name!r}"
                ))
                ok = False
            elif b.name not in w.groups:
                out.append(Diagnostic("group", path, f"unknown group {b.name!r}"))
                ok = False
    colors: dict[str, int] = {}  # 0 = on the current DFS path, 1 = fully explored

    def visit(name: str, stack: tuple[str, ...]) -> None:
        nonlocal ok
        state = colors.get(name)
        if state == 1:
            return
        if state == 0:
            cycle = " -> ".join((*stack[stack.index(name):], name))
            out.append(Diagnostic("group", f"groups[{name!r}]", f"recursive group: {cycle}"))
            ok = False
            return
        colors[name] = 0
        for _, b in _iter_blocks(w.groups[name].body, ""):
            if isinstance(b, B.GroupRef) and b.name in w.groups:
                visit(b.name, (*stack, name))
        colors[name] = 1

    for name in w.groups:
        visit(name, ())
    return ok


def _uses_macros(w: Workflow) -> bool:
    if any(g.params for g in w.groups.values()):
        return True
    for _, b in _iter_all_blocks(w):
        if isinstance(b, B.ForEach):
            return True
        if isinstance(b, B.GroupRef) and b.args:
            return True
    return False


def _check_for_each_and_arity(w: Workflow, out: list[Diagnostic]) -> bool:
    ok = True
    for path, b in _iter_all_blocks(w):
        if isinstance(b, B.ForEach):
            for key, present in (("retry", b.retry is not None), ("on_error", b.on_error != "fail"),
                                 ("gap_after", b.gap_after is not None),
                                 ("start_offset", b.start_offset is not None)):
                if present:
                    out.append(Diagnostic(
                        "for_each", path,
                        f"for_each may not carry block-level {key!r}; put it on the body blocks",
                    ))
                    ok = False
            if not b.body:
                out.append(Diagnostic("for_each", path, "for_each 'body' must be non-empty"))
                ok = False
            if not b.items:
                out.append(Diagnostic("for_each", path, "for_each 'in' must be non-empty"))
                ok = False
            scalar = [i for i in b.items if not isinstance(i, dict)]
            objects = [i for i in b.items if isinstance(i, dict)]
            if b.var is not None and objects:
                out.append(Diagnostic(
                    "for_each", path, "for_each with 'var' requires scalar items"))
                ok = False
            if b.var is None and scalar:
                out.append(Diagnostic(
                    "for_each", path, "for_each without 'var' requires object items"))
                ok = False
        elif isinstance(b, B.GroupRef):
            group = w.groups.get(b.name)
            # Group.params is list[ParamDecl] as of the typed-declaration data model
            # (design 2026-07-20 §2.1); this arity check only needs the declared names.
            params = {p.name for p in group.params} if group is not None else set()
            if group is not None and set(b.args) != params:
                out.append(Diagnostic(
                    "group", path,
                    f"group_ref {b.name!r}: args {sorted(b.args)} must match params "
                    f"{sorted(params)}",
                ))
                ok = False
    return ok


_INPUT_TYPES: dict[str, BindingType] = {
    "float": "number",
    "int": "number",
    "bool": "boolean",
    "enum": "string",
}


def _collect_binding_types(w: Workflow) -> dict[str, BindingType]:
    """Declared type of every operator-input binding; conflicts degrade to 'unknown'."""
    types: dict[str, BindingType] = {}
    for _, b in _iter_all_blocks(w):
        if not isinstance(b, B.OperatorInput) or not isinstance(b.name, str):
            continue
        t = _INPUT_TYPES.get(b.type, "unknown") if isinstance(b.type, str) else "unknown"
        if b.name in types:
            if types[b.name] != t:
                types[b.name] = "unknown"
        else:
            types[b.name] = t
    return types


def _check_expr_type(
    text: str,
    expected: ExprType,
    ctx: str,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    try:
        expr = parse_expression(text)
    except ExpressionError as exc:
        out.append(Diagnostic("type", ctx, f"invalid expression: {exc}"))
        return
    report = infer_type(expr, binding_types)
    for problem in report.problems:
        out.append(Diagnostic("type", ctx, problem))
    if report.type not in (expected, "unknown"):
        out.append(Diagnostic(
            "type", ctx, f"expected a {expected} expression, got {report.type}"
        ))


def _check_param_value(
    spec: ParamSpec,
    value: object,
    ctx: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    """Check one param value against its spec, including stream declarations
    referenced by stat calls in expression values."""
    if spec.kind == "string":
        if not isinstance(value, str):
            out.append(Diagnostic("params", ctx, f"expected a string literal, got {value!r}"))
        return
    if isinstance(value, str):
        expected: ExprType = "boolean" if spec.kind == "bool" else "number"
        _check_expr_type(value, expected, ctx, binding_types, out)
        _check_streams_declared(value, ctx, w, out)
        return
    if spec.kind == "bool":
        if not isinstance(value, bool):
            out.append(Diagnostic("params", ctx, f"expected a boolean, got {value!r}"))
    elif spec.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            out.append(Diagnostic("params", ctx, f"expected an integer, got {value!r}"))
    else:  # number
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            out.append(Diagnostic("params", ctx, f"expected a number, got {value!r}"))


def _check_action(
    b: B.Command | B.Measure,
    path: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    try:
        trait = lookup(legacy_device_type(b.device), b.verb)
    except UnknownVerbError as exc:
        out.append(Diagnostic("registry", path, str(exc)))
        return
    specs = {s.name: s for s in trait.params}
    for name, value in b.params.items():
        spec = specs.get(name)
        if spec is None:
            out.append(Diagnostic("params", path, f"unknown param {name!r} for verb {b.verb!r}"))
            continue
        _check_param_value(spec, value, f"{path} param {name!r}", w, binding_types, out)
    for spec in trait.params:
        if spec.required and spec.name not in b.params:
            out.append(Diagnostic(
                "params", path, f"missing required param {spec.name!r} for verb {b.verb!r}"
            ))


_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_RESERVED_NAMES = frozenset({"and", "or", "not", "true", "false"})


def _check_streams_declared(text: str, ctx: str, w: Workflow, out: list[Diagnostic]) -> None:
    try:
        expr = parse_expression(text)
    except ExpressionError:
        return  # unparseable strings are already diagnosed by the type check
    refs = references(expr)
    for stream in sorted(refs.streams_windowed | refs.streams_counted):
        if stream not in w.streams:
            out.append(Diagnostic(
                "declaration", ctx, f"stat references undeclared stream {stream!r}"
            ))


def _check_condition(
    text: object,
    ctx: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    if not isinstance(text, str):
        out.append(Diagnostic(
            "type", ctx, f"condition must be an expression string, got {text!r}"
        ))
        return
    _check_expr_type(text, "boolean", ctx, binding_types, out)
    _check_streams_declared(text, ctx, w, out)


def _check_message(message: object, path: str, kind: str, out: list[Diagnostic]) -> None:
    if not isinstance(message, str) or not message.strip():
        out.append(Diagnostic("block", path, f"{kind} requires a non-empty message"))


def _check_compute_value(
    value: object,
    ctx: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    """compute stores a number OR a boolean; accept either, surface enum-string refs."""
    if not isinstance(value, str):
        if isinstance(value, bool) or isinstance(value, (int, float)):
            return
        out.append(Diagnostic(
            "type", ctx, f"compute value must be a number, boolean, or expression, got {value!r}"
        ))
        return
    try:
        expr = parse_expression(value)
    except ExpressionError as exc:
        out.append(Diagnostic("type", ctx, f"invalid expression: {exc}"))
        return
    for problem in infer_type(expr, binding_types).problems:
        out.append(Diagnostic("type", ctx, problem))
    _check_streams_declared(value, ctx, w, out)


def _check_record_value(
    value: object,
    ctx: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    """record stores a number; a boolean literal or a boolean expression is an error."""
    if not isinstance(value, str):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            out.append(Diagnostic(
                "type", ctx, f"record value must be a number or expression, got {value!r}"
            ))
        return
    _check_expr_type(value, "number", ctx, binding_types, out)
    _check_streams_declared(value, ctx, w, out)


def _check_compute(
    b: B.Compute,
    path: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    usable = (
        isinstance(b.into, str)
        and _IDENT_RE.fullmatch(b.into) is not None
        and b.into not in _RESERVED_NAMES
    )
    if not usable:
        out.append(Diagnostic(
            "block", path, f"compute into {b.into!r} is not a usable binding name"
        ))
    _check_compute_value(b.value, f"{path} compute value", w, binding_types, out)


def _check_record(
    b: B.Record,
    path: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    if not isinstance(b.into, str):
        out.append(Diagnostic(
            "block", path, f"record into must be a stream name, got {b.into!r}"
        ))
    elif b.into not in w.streams:
        out.append(Diagnostic(
            "declaration", path, f"record writes undeclared stream {b.into!r}"
        ))
    _check_record_value(b.value, f"{path} record value", w, binding_types, out)


def _check_measure(b: B.Measure, path: str, w: Workflow, out: list[Diagnostic]) -> None:
    try:
        trait = lookup(legacy_device_type(b.device), b.verb)
    except UnknownVerbError:
        return  # already diagnosed by _check_action
    if not trait.measurement:
        out.append(Diagnostic(
            "block", path, f"measure requires a measurement verb, got {b.verb!r}"
        ))
    if not isinstance(b.into, str):
        out.append(Diagnostic(
            "block", path, f"measure into must be a stream name, got {b.into!r}"
        ))
    elif b.into not in w.streams:
        out.append(Diagnostic(
            "declaration", path, f"measure writes undeclared stream {b.into!r}"
        ))


def _check_operator_input(b: B.OperatorInput, path: str, out: list[Diagnostic]) -> None:
    usable = (
        isinstance(b.name, str)
        and _IDENT_RE.fullmatch(b.name) is not None
        and b.name not in _RESERVED_NAMES
    )
    if not usable:
        out.append(Diagnostic(
            "block", path, f"operator_input name {b.name!r} is not a usable binding name"
        ))
    if not isinstance(b.type, str) or b.type not in _INPUT_TYPES:
        out.append(Diagnostic(
            "block", path,
            f"operator_input type must be one of float, int, enum, bool; got {b.type!r}",
        ))
        return
    numeric = b.type in ("float", "int")
    if b.type == "enum":
        if not isinstance(b.choices, list) or not b.choices or not all(
            isinstance(c, str) for c in b.choices
        ):
            out.append(Diagnostic(
                "block", path, "enum operator_input requires a non-empty list of string choices"
            ))
    elif b.choices is not None:
        out.append(Diagnostic(
            "block", path, f"choices are only valid for enum operator_input, not {b.type!r}"
        ))
    for attr in ("min", "max"):
        value = getattr(b, attr)
        if value is None:
            continue
        if not numeric:
            out.append(Diagnostic(
                "block", path, f"{attr} is only valid for float/int operator_input"
            ))
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            out.append(Diagnostic("block", path, f"{attr} must be a number, got {value!r}"))
    if (
        isinstance(b.min, (int, float)) and not isinstance(b.min, bool)
        and isinstance(b.max, (int, float)) and not isinstance(b.max, bool)
        and b.min > b.max
    ):
        out.append(Diagnostic("block", path, f"min {b.min} exceeds max {b.max}"))


def _check_loop(
    b: B.Loop,
    path: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    has_count = b.count is not None
    has_until = b.until is not None
    if has_count == has_until:
        out.append(Diagnostic("block", path, "loop requires exactly one of count or until"))
    if has_count:
        if isinstance(b.count, bool) or not isinstance(b.count, int):
            out.append(Diagnostic(
                "block", path, f"loop count must be an integer, got {b.count!r}"
            ))
        elif b.count < 1:
            out.append(Diagnostic("block", path, f"loop count must be >= 1, got {b.count}"))
    if b.check not in ("before", "after"):
        out.append(Diagnostic(
            "block", path, f"loop check must be 'before' or 'after', got {b.check!r}"
        ))
    if has_until:
        _check_condition(b.until, f"{path} loop until", w, binding_types, out)


def _check_on_error(block: B.Block, path: str, out: list[Diagnostic]) -> None:
    """Legal on every block type (design 2026-07-14 §2.2)."""
    if block.on_error not in B.ON_ERROR_VALUES:
        out.append(Diagnostic(
            "block", path,
            f"on_error must be one of {B.ON_ERROR_VALUES}, got {block.on_error!r}",
        ))


def _check_retry(block: B.Block, path: str, out: list[Diagnostic]) -> None:
    """retry is command/measure only, and a non-idempotent verb needs an explicit
    in-document opt-in (design 2026-07-14 §4)."""
    retry = block.retry
    if retry is None:
        return
    # The loader enforces attempts >= 1, but a Retry built through the Python API bypasses it,
    # and attempts=0 would run the block zero times (the executor's "unreachable" branch).
    if retry.attempts < 1:
        out.append(Diagnostic(
            "block", path, f"retry.attempts must be >= 1, got {retry.attempts}",
        ))
    if not isinstance(block, (B.Command, B.Measure)):
        out.append(Diagnostic(
            "block", path, "retry is only valid on command and measure blocks"
        ))
        return
    try:
        trait = lookup(legacy_device_type(block.device), block.verb)
    except UnknownVerbError:
        return  # already diagnosed by _check_action
    if not trait.retry_safe and not retry.allow_repeat:
        out.append(Diagnostic(
            "block", path,
            f"verb {block.verb!r} on {block.device!r} is not idempotent; a retry after a "
            f"partial action may repeat it. Set retry.allow_repeat=true to accept this.",
        ))


def _check_defaults(w: Workflow, out: list[Diagnostic]) -> None:
    retry = w.defaults.retry
    if retry is None:
        return
    if retry.allow_repeat:
        out.append(Diagnostic(
            "block", "defaults.retry",
            "defaults.retry may not set allow_repeat; a blanket policy must never retry a "
            "non-idempotent verb",
        ))
    if retry.attempts < 1:  # see _check_retry: the loader enforces this, the Python API does not
        out.append(Diagnostic(
            "block", "defaults.retry",
            f"retry.attempts must be >= 1, got {retry.attempts}",
        ))


def _check_namespaces(w: Workflow, out: list[Diagnostic]) -> None:
    """Disjointness across the binding and stream namespaces (design §6)."""
    measure_streams: set[str] = set()
    record_streams: set[str] = set()
    input_names: set[str] = set()
    compute_names: set[str] = set()
    for _, b in _iter_all_blocks(w):
        if isinstance(b, B.Measure) and isinstance(b.into, str):
            measure_streams.add(b.into)
        elif isinstance(b, B.Record) and isinstance(b.into, str):
            record_streams.add(b.into)
        elif isinstance(b, B.OperatorInput) and isinstance(b.name, str):
            input_names.add(b.name)
        elif isinstance(b, B.Compute) and isinstance(b.into, str):
            compute_names.add(b.into)
    binding_names = input_names | compute_names
    declared = set(w.streams)
    for s in sorted(measure_streams & record_streams):
        out.append(Diagnostic(
            "declaration", "streams",
            f"stream {s!r} is written by both measure and record; a stream is measured "
            f"or computed, never both",
        ))
    for n in sorted(binding_names & declared):
        out.append(Diagnostic(
            "declaration", "names",
            f"name {n!r} is used as both a scalar binding and a stream",
        ))
    for n in sorted(compute_names & input_names):
        out.append(Diagnostic(
            "declaration", "bindings",
            f"name {n!r} is written by both operator_input and compute; a binding has "
            f"one kind of writer",
        ))


def _check_block(
    block: B.Block,
    path: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    # Unconditional: legal on every block type, including Serial/Parallel/Wait/GroupRef,
    # which reach none of the type-specific checks below.
    _check_on_error(block, path, out)
    _check_retry(block, path, out)
    if isinstance(block, (B.Command, B.Measure)):
        _check_action(block, path, w, binding_types, out)
    if isinstance(block, B.Measure):
        _check_measure(block, path, w, out)
    elif isinstance(block, B.OperatorInput):
        _check_operator_input(block, path, out)
    elif isinstance(block, B.Loop):
        _check_loop(block, path, w, binding_types, out)
    elif isinstance(block, B.Branch):
        _check_condition(block.if_, f"{path} branch if", w, binding_types, out)
    elif isinstance(block, B.Compute):
        _check_compute(block, path, w, binding_types, out)
    elif isinstance(block, B.Record):
        _check_record(block, path, w, binding_types, out)
    elif isinstance(block, B.Abort):
        _check_condition(block.if_, f"{path} abort if", w, binding_types, out)
        _check_message(block.message, path, "abort", out)
        if block.on_error == "continue":
            out.append(Diagnostic(
                "block", path,
                "abort may not carry on_error: 'continue'; a safety stop cannot be tolerated",
            ))
    elif isinstance(block, B.Alarm):
        _check_condition(block.if_, f"{path} alarm if", w, binding_types, out)
        _check_message(block.message, path, "alarm", out)


@dataclass
class _PathState:
    """Abstract state along one control-flow path (design §12)."""

    bindings: set[str] = field(default_factory=set)  # definitely written by operator_input
    streams: set[str] = field(default_factory=set)  # definitely written by a measure
    # Streams an enclosing `branch` guard proved to hold >= 1 sample. Strictly weaker than
    # `streams`: it discharges whole-stream and sample-count reads, never a duration window
    # (design 2026-07-14 §5.2). Durable, because Stream is append-only.
    nonempty: set[str] = field(default_factory=set)
    modes: dict[tuple[str, str], str] = field(default_factory=dict)
    # modes: (device_id, mode_verb) -> "open" | "maybe"; absent = closed

    def copy(self) -> _PathState:
        return _PathState(
            set(self.bindings), set(self.streams), set(self.nonempty), dict(self.modes)
        )


def _merge(a: _PathState, b: _PathState) -> _PathState:
    """Join at a control-flow merge: definitely-written = written on both sides;
    a mode is open only if open on both, else possibly open (may-open tracking)."""
    modes: dict[tuple[str, str], str] = {}
    for key in a.modes.keys() | b.modes.keys():
        sa, sb = a.modes.get(key), b.modes.get(key)
        modes[key] = "open" if sa == "open" and sb == "open" else "maybe"
    return _PathState(
        a.bindings & b.bindings, a.streams & b.streams, a.nonempty & b.nonempty, modes
    )


@dataclass
class _Ctx:
    workflow: Workflow
    out: list[Diagnostic]
    seen: set[tuple[str, str, str]] = field(default_factory=set)

    def emit(self, category: str, path: str, message: str) -> None:
        """Append a diagnostic once; loop re-analysis legitimately revisits blocks."""
        key = (category, path, message)
        if key not in self.seen:
            self.seen.add(key)
            self.out.append(Diagnostic(category, path, message))


def _window_text(w: Window) -> str:
    """Render a window the way an author would have written it."""
    if isinstance(w, SampleWindow):
        return f"last={w.n}"
    if isinstance(w, DurationWindow):
        shown = int(w.seconds) if w.seconds == int(w.seconds) else w.seconds
        return f"last={shown}s"
    return "whole stream"


def _expr_reads(text: object, ctx: str, state: _PathState, c: _Ctx) -> None:
    """Check one expression slot's reads against the current path state."""
    if not isinstance(text, str):
        return  # literals read nothing; non-string garbage is diagnosed globally
    try:
        expr = parse_expression(text)
    except ExpressionError:
        return  # already diagnosed globally
    # A guard carried in from an enclosing branch has decayed to the stream-level fact.
    proven: dict[str, Window] = {stream: AllWindow() for stream in state.nonempty}
    _expr_reads_ast(expr, ctx, state.bindings, state.streams, proven, c)


def _expr_reads_ast(
    expr: Expr,
    ctx: str,
    bindings: set[str],
    streams: set[str],
    proven: ProvenWindows,
    c: _Ctx,
) -> None:
    """Walk `and` chains left-to-right so a `count(S, W) > 0` guard extends the proof set
    for everything to its right — mirroring the evaluator's short-circuit. One `evaluate`
    call threads a single `now`, so a duration proof holds for the whole expression
    (design 2026-07-14 §5.2)."""
    if isinstance(expr, BinaryOp) and expr.op == "and":
        _expr_reads_ast(expr.left, ctx, bindings, streams, proven, c)
        guarded = conjoin_proofs(proven, proven_nonempty(expr.left))
        _expr_reads_ast(expr.right, ctx, bindings, streams, guarded, c)
        return
    for name in sorted(references(expr).bindings - bindings):
        c.emit("data-flow", ctx, f"binding {name!r} may be read before it is written")
    reads = sorted(windowed_reads(expr), key=lambda r: (r.stream, _window_text(r.window)))
    for read in reads:
        # A definite prior measure discharges any window — including a duration window it
        # does not strictly prove non-empty. That concession predates guard refinement and
        # is deliberately preserved; see the design's §5.2 note.
        if read.stream in streams or read.stream not in c.workflow.streams:
            continue  # definitely written, or undeclared (already diagnosed)
        held = proven.get(read.stream)
        if held is None:
            c.emit(
                "data-flow", ctx,
                f"stat over stream {read.stream!r} has no preceding measure on some path",
            )
        elif not proof_covers(held, read.window):
            window = _window_text(read.window)
            c.emit(
                "data-flow", ctx,
                f"stat over stream {read.stream!r} reads a duration window ({window}) that "
                f"the guard does not prove non-empty; guard it with "
                f"count({read.stream}, {window}) > 0",
            )


def _durable_guard_proof(condition: str) -> set[str]:
    """Streams a `branch` condition proves non-empty *for the whole body it guards*.

    Only the stream-level fact ">= 1 sample" survives the crossing: it is durable because
    `Stream` is append-only, and every guard form implies it. A *duration* proof does not
    survive — `now` advances while the body runs, so `count(S, last=5min) > 0` followed by
    `wait: 10min` and a `mean(S, last=5min)` would read an empty window. Inside a single
    expression the duration proof does hold, and `_expr_reads_ast` uses it there.
    """
    try:
        return set(proven_nonempty(parse_expression(condition)))
    except ExpressionError:
        return set()  # unparseable: already diagnosed globally


def _visit_action(b: B.Command | B.Measure, path: str, state: _PathState, c: _Ctx) -> None:
    try:
        trait = lookup(legacy_device_type(b.device), b.verb)
    except UnknownVerbError:
        return  # already diagnosed globally; nothing to analyze against
    specs = {s.name: s for s in trait.params}
    for name, value in b.params.items():
        spec = specs.get(name)
        if spec is not None and spec.kind != "string":
            _expr_reads(value, f"{path} param {name!r}", state, c)
    action = mode_action(legacy_device_type(b.device), b.verb, b.params)
    if action is not None and action.kind == "close":
        # A matching close is always legal: closes if open, no-ops if not (design §12).
        state.modes.pop((b.device, action.mode_verb), None)
    else:
        for (device, mode_verb), status in sorted(state.modes.items()):
            if device != b.device:
                continue
            if lookup(legacy_device_type(device), mode_verb).channels & trait.channels:
                word = "open" if status == "open" else "possibly open"
                c.emit(
                    "mode", path,
                    f"{b.verb!r} on {b.device!r} falls inside the {word} interval of "
                    f"mode {mode_verb!r}",
                )
        if action is not None:
            state.modes[(b.device, action.mode_verb)] = "open"
    if isinstance(b, B.Measure) and isinstance(b.into, str):
        state.streams.add(b.into)


def _visit_loop(b: B.Loop, path: str, state: _PathState, c: _Ctx) -> _PathState:
    body_path = f"{path}.body"
    until_ctx = f"{path} loop until"
    count = b.count if isinstance(b.count, int) and not isinstance(b.count, bool) else None
    if b.until is not None:
        repeats, guaranteed = True, b.check != "before"
    elif count is not None and count >= 1:
        repeats, guaranteed = count > 1, True
    else:  # invalid loop fields (diagnosed globally): assume the worst on both axes
        repeats, guaranteed = True, False
    if b.until is not None and b.check == "before":
        _expr_reads(b.until, until_ctx, state, c)  # pre-test: first check sees entry only
    exit_state = _visit_blocks(b.body, body_path, state.copy(), c)
    if b.until is not None and b.check != "before":
        _expr_reads(b.until, until_ctx, exit_state, c)  # post-test: check sees body writes
    result = exit_state
    if repeats:
        # Back edge: iteration k+1 starts from iteration k's exit. Re-analyze to a
        # fixpoint (the abstract state space is tiny); _Ctx.emit dedupes repeats.
        prev = exit_state
        for _ in range(3):
            nxt = _visit_blocks(b.body, body_path, prev.copy(), c)
            if b.until is not None and b.check != "before":
                _expr_reads(b.until, until_ctx, nxt, c)
            result = _merge(result, nxt)
            if nxt == prev:
                break
            prev = nxt
    if not guaranteed:
        result = _merge(state, result)  # zero iterations possible: entry state survives
    return result


def _footprint(root: B.Block, w: Workflow) -> set[tuple[str, str]]:
    """Every (device, channel) a subtree can command on any reachable path (groups
    inlined; the path phase only runs when the group graph is acyclic)."""
    found: set[tuple[str, str]] = set()
    stack: list[B.Block] = [root]
    while stack:
        b = stack.pop()
        if isinstance(b, (B.Command, B.Measure)):
            try:
                trait = lookup(legacy_device_type(b.device), b.verb)
            except UnknownVerbError:
                continue
            found.update((b.device, ch) for ch in trait.channels)
        elif isinstance(b, (B.Serial, B.Parallel)):
            stack.extend(b.children)
        elif isinstance(b, B.Loop):
            stack.extend(b.body)
        elif isinstance(b, B.Branch):
            stack.extend(b.then)
            if b.else_ is not None:
                stack.extend(b.else_)
        elif isinstance(b, B.GroupRef):
            group = w.groups.get(b.name)
            if group is not None:
                stack.extend(group.body)
    return found


def _visit_parallel(b: B.Parallel, path: str, state: _PathState, c: _Ctx) -> _PathState:
    footprints = [_footprint(child, c.workflow) for child in b.children]
    for i in range(len(b.children)):
        for j in range(i + 1, len(b.children)):
            for device, channel in sorted(footprints[i] & footprints[j]):
                c.emit(
                    "affinity", path,
                    f"parallel children [{i}] and [{j}] both command device {device!r} "
                    f"channel {channel!r}",
                )
    entry_modes = dict(state.modes)
    exits = []
    for i, child in enumerate(b.children):
        # Each concurrent lane sees only the entry state plus its own writes:
        # sibling writes are unordered relative to this lane (design §12).
        exits.append(_visit(child, f"{path}.children[{i}]", state.copy(), c))
    for e in exits:  # the container completes when every lane does: union of writes
        state.bindings |= e.bindings
        state.streams |= e.streams
        # No-op, by induction: `Branch` is the only place `nonempty` ever grows, and
        # `_merge` immediately intersects it back out at that same branch's exit, so a
        # lane's exit `nonempty` always equals its entry `nonempty` (the shared `state`
        # copied into every lane, per the comment above). Kept, and spelled out, so a
        # future reader does not "fix" this into cross-lane proof sharing — that would be
        # unsound: sibling lanes are unordered, so one lane's guard proves nothing about
        # whether another lane's measure ran.
        state.nonempty |= e.nonempty
        # Footprint disjointness means each lane owns the modes it touches:
        # apply every lane's delta against the shared entry.
        for key in e.modes.keys() - entry_modes.keys():
            state.modes[key] = e.modes[key]
        for key in entry_modes.keys() - e.modes.keys():
            state.modes.pop(key, None)
        for key in entry_modes.keys() & e.modes.keys():
            if e.modes[key] != entry_modes[key]:
                state.modes[key] = e.modes[key]
    return state


def _visit(b: B.Block, path: str, state: _PathState, c: _Ctx) -> _PathState:
    entry = state.copy() if b.on_error == "continue" else None
    state = _visit_body(b, path, state, c)
    if entry is not None:
        # A tolerated failure can skip this block's writes entirely: join like a branch
        # with an empty else (design 2026-07-14 §5.2).
        state = _merge(entry, state)
    return state


def _visit_body(b: B.Block, path: str, state: _PathState, c: _Ctx) -> _PathState:
    if isinstance(b, (B.Command, B.Measure)):
        _visit_action(b, path, state, c)
    elif isinstance(b, B.OperatorInput):
        if isinstance(b.name, str):
            state.bindings.add(b.name)
    elif isinstance(b, B.Serial):
        state = _visit_blocks(b.children, f"{path}.children", state, c)
    elif isinstance(b, B.Parallel):
        state = _visit_parallel(b, path, state, c)
    elif isinstance(b, B.Loop):
        state = _visit_loop(b, path, state, c)
    elif isinstance(b, B.Branch):
        _expr_reads(b.if_, f"{path} branch if", state, c)
        then_state = state.copy()
        if isinstance(b.if_, str):
            then_state.nonempty |= _durable_guard_proof(b.if_)
        then_state = _visit_blocks(b.then, f"{path}.then", then_state, c)
        else_state = _visit_blocks(b.else_ or [], f"{path}.else", state.copy(), c)
        state = _merge(then_state, else_state)
    elif isinstance(b, B.Compute):
        _expr_reads(b.value, f"{path} compute value", state, c)
        if isinstance(b.into, str):
            state.bindings.add(b.into)
    elif isinstance(b, B.Record):
        _expr_reads(b.value, f"{path} record value", state, c)
        if isinstance(b.into, str):
            state.streams.add(b.into)
    elif isinstance(b, (B.Abort, B.Alarm)):
        slot = "abort if" if isinstance(b, B.Abort) else "alarm if"
        _expr_reads(b.if_, f"{path} {slot}", state, c)
    elif isinstance(b, B.GroupRef):
        group = c.workflow.groups.get(b.name)
        if group is not None:  # unknown refs are diagnosed globally; phase is gated anyway
            state = _visit_blocks(group.body, f"{path}->{b.name}.body", state, c)
    return state  # Wait blocks fall through unchanged


def _visit_blocks(blocks: list[B.Block], prefix: str, state: _PathState, c: _Ctx) -> _PathState:
    for i, b in enumerate(blocks):
        state = _visit(b, f"{prefix}[{i}]", state, c)
    return state


def _analyze_paths(w: Workflow, out: list[Diagnostic]) -> None:
    _visit_blocks(w.blocks, "blocks", _PathState(), _Ctx(w, out))


def _check_abort_not_under_tolerance(w: Workflow, out: list[Diagnostic]) -> None:
    """An `abort` may not sit under an `on_error: "continue"` ancestor, at any depth: a
    tolerant ancestor can absorb the abort's own condition-eval failure (a divide-by-zero,
    a non-finite result, a type fault — none of which the freshness analysis catches) and
    silently disable the safety stop. This mirrors, transitively, the existing prohibition
    on the abort's own `on_error` (`_check_block`'s `B.Abort` arm). Only ever called on an
    expandable workflow (gated like `_analyze_paths`), so group refs are acyclic and this
    recursion terminates."""

    def visit(blocks: list[B.Block], prefix: str, under_tolerance: bool) -> None:
        for i, b in enumerate(blocks):
            path = f"{prefix}[{i}]"
            if isinstance(b, B.Abort) and under_tolerance:
                out.append(Diagnostic(
                    "block", path,
                    "abort has an on_error: 'continue' ancestor; a tolerant ancestor can "
                    "absorb the abort's condition-eval failure and silently disable the "
                    "safety stop — remove the tolerance from the ancestor, or move the "
                    "abort out of the tolerant subtree",
                ))
            child_tolerance = under_tolerance or (b.on_error == "continue")
            if isinstance(b, (B.Serial, B.Parallel)):
                visit(b.children, f"{path}.children", child_tolerance)
            elif isinstance(b, B.Loop):
                visit(b.body, f"{path}.body", child_tolerance)
            elif isinstance(b, B.Branch):
                visit(b.then, f"{path}.then", child_tolerance)
                if b.else_ is not None:
                    visit(b.else_, f"{path}.else", child_tolerance)
            elif isinstance(b, B.GroupRef):
                group = w.groups.get(b.name)
                if group is not None:
                    visit(group.body, f"{path}->{b.name}.body", child_tolerance)

    visit(w.blocks, "blocks", False)


def validate(workflow: Workflow) -> None:
    """Statically validate a loaded workflow (design §11 phase 2, rules §12).

    Macro docs (for_each / parametrized groups) are expanded first and every concrete
    check runs on the expansion; legacy docs validate in place, unchanged.
    """
    out: list[Diagnostic] = []
    if not _uses_macros(workflow):
        _validate_workflow(workflow, out)
    else:
        _validate_macro_workflow(workflow, out)
    if out:
        raise ValidationError(out)


def _validate_workflow(workflow: Workflow, out: list[Diagnostic]) -> None:
    """Collects every violation into `out`. The path-sensitive phase is skipped when
    group references cannot be resolved (unknown or recursive groups) — the tree cannot
    be soundly expanded."""
    expandable = _check_groups(workflow, out)
    _check_defaults(workflow, out)
    _check_namespaces(workflow, out)
    binding_types = _collect_binding_types(workflow)
    for path, block in _iter_all_blocks(workflow):
        _check_block(block, path, workflow, binding_types, out)
    if expandable:
        _analyze_paths(workflow, out)
        _check_abort_not_under_tolerance(workflow, out)


def _validate_macro_workflow(workflow: Workflow, out: list[Diagnostic]) -> None:
    """Gate the authored (templated) doc, then expand and run every concrete check on
    the expansion. The authored blocks (holes, for_each, parametrized group_refs) never
    reach the concrete checks — only `_check_groups` and `_check_for_each_and_arity` see
    them; `_validate_workflow` below only ever sees the macro-free `expanded` doc."""
    expandable = _check_groups(workflow, out)
    expandable = _check_for_each_and_arity(workflow, out) and expandable
    if not expandable:
        _check_defaults(workflow, out)
        return
    try:
        expanded = expand_workflow(workflow)
    except WorkflowLoadError as exc:
        _check_defaults(workflow, out)
        out.append(Diagnostic("expansion", "blocks", str(exc)))
        return
    _validate_workflow(expanded, out)  # this covers _check_defaults on the success path


def load_and_validate(path: str | Path) -> Workflow:
    """Load a workflow document and statically validate it (design §11 phases 1-2)."""
    workflow = load_workflow(path)
    validate(workflow)
    return workflow
