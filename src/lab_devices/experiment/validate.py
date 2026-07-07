"""Static workflow validator: registry, affinity, mode lifetimes, data-flow. See design §12."""

from __future__ import annotations

from collections.abc import Iterator, Mapping

from lab_devices.experiment import blocks as B
from lab_devices.experiment.analyze import BindingType, ExprType, infer_type
from lab_devices.experiment.errors import (
    Diagnostic,
    ExpressionError,
    UnknownVerbError,
    ValidationError,
)
from lab_devices.experiment.expr import parse_expression
from lab_devices.experiment.registry import ParamSpec, lookup
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


def _iter_all_blocks(w: Workflow) -> Iterator[tuple[str, B.Block]]:
    yield from _iter_blocks(w.blocks, "blocks")
    for name, group in w.groups.items():
        yield from _iter_blocks(group.body, f"groups[{name!r}].body")


def _check_groups(w: Workflow, out: list[Diagnostic]) -> bool:
    """Unknown group refs and self/mutual recursion (design §12); True iff expandable."""
    ok = True
    for path, b in _iter_all_blocks(w):
        if isinstance(b, B.GroupRef) and b.name not in w.groups:
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
        t = _INPUT_TYPES.get(b.type, "unknown")
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
    """Check one param value against its spec. The w parameter feeds the Task 6
    stream-declaration check; it is deliberately unused until then."""
    if spec.kind == "string":
        if not isinstance(value, str):
            out.append(Diagnostic("params", ctx, f"expected a string literal, got {value!r}"))
        return
    if isinstance(value, str):
        expected: ExprType = "boolean" if spec.kind == "bool" else "number"
        _check_expr_type(value, expected, ctx, binding_types, out)
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
        trait = lookup(b.device, b.verb)
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


def _check_block(
    block: B.Block,
    path: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    if isinstance(block, (B.Command, B.Measure)):
        _check_action(block, path, w, binding_types, out)


def validate(workflow: Workflow) -> None:
    """Statically validate a loaded workflow (design §11 phase 2, rules §12).

    Collects every violation and raises one ValidationError; returns None when clean.
    """
    out: list[Diagnostic] = []
    _check_groups(workflow, out)
    binding_types = _collect_binding_types(workflow)
    for path, block in _iter_all_blocks(workflow):
        _check_block(block, path, workflow, binding_types, out)
    if out:
        raise ValidationError(out)
