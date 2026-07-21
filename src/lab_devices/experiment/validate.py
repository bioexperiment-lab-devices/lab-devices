"""Static workflow validator: registry, affinity, mode lifetimes, data-flow. See design §12."""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from lab_devices.experiment import blocks as B
from lab_devices.experiment.analyze import (
    BindingType,
    ExprType,
    ProvenWindows,
    assignable,
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
from lab_devices.experiment.workflow import (
    REFERENCE_KINDS,
    Group,
    LocalDecl,
    ParamDecl,
    Workflow,
)


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


def _is_plain(group: Group) -> bool:
    """A PLAIN group -- no params, no locals -- is the one expand.py lazily inlines: its
    body is expanded once, eagerly, regardless of how many group_refs later name it."""
    return not group.params and not group.locals


def _body_reaches_locals_ref(w: Workflow, blocks: list[B.Block], seen: set[str]) -> bool:
    for b in blocks:
        if isinstance(b, B.GroupRef):
            target = w.groups.get(b.name)
            if target is None:
                continue
            if target.locals:
                return True
            # Recurse regardless of whether `target` is plain: a PARAMETRIZED
            # intermediate's body is substituted with fixed args as part of the
            # enclosing plain group's single eager expansion, so a locals-bearing ref
            # nested past it is just as much a hazard as one nested past another plain
            # group (fixed 2026-07-20; previously gated on `_is_plain(target)`, which
            # missed the plain -> parametrized -> locals-bearing chain entirely).
            if _group_reaches_locals_ref(w, b.name, seen):
                return True
        elif isinstance(b, B.ForEach):
            if _body_reaches_locals_ref(w, b.body, seen):
                return True
        elif isinstance(b, (B.Serial, B.Parallel)):
            if _body_reaches_locals_ref(w, b.children, seen):
                return True
        elif isinstance(b, B.Loop):
            if _body_reaches_locals_ref(w, b.body, seen):
                return True
        elif isinstance(b, B.Branch):
            if _body_reaches_locals_ref(w, b.then, seen):
                return True
            if b.else_ is not None and _body_reaches_locals_ref(w, b.else_, seen):
                return True
    return False


def _group_reaches_locals_ref(w: Workflow, name: str, seen: set[str]) -> bool:
    """True if the group named `name`'s body -- transitively, through further group_refs
    it contains, whether those name plain or parametrized groups -- reaches a group_ref
    naming a group that declares locals. `seen` guards a group cycle (already reported by
    _check_groups) by treating a revisit as False rather than recursing forever."""
    if name in seen:
        return False
    seen.add(name)
    group = w.groups.get(name)
    if group is None:
        return False
    return _body_reaches_locals_ref(w, group.body, seen)


def _ref_count(blocks: list[B.Block], name: str, weight: int) -> int:
    """Occurrences of `group_ref {name}` reachable from `blocks`, weighted by every
    enclosing for_each's row count -- known statically, since `items` is authored data,
    not runtime-parametrized."""
    total = 0
    for b in blocks:
        if isinstance(b, B.GroupRef) and b.name == name:
            total += weight
        if isinstance(b, B.ForEach):
            total += _ref_count(b.body, name, weight * max(len(b.items), 1))
        elif isinstance(b, (B.Serial, B.Parallel)):
            total += _ref_count(b.children, name, weight)
        elif isinstance(b, B.Loop):
            total += _ref_count(b.body, name, weight)
        elif isinstance(b, B.Branch):
            total += _ref_count(b.then, name, weight)
            if b.else_ is not None:
                total += _ref_count(b.else_, name, weight)
    return total


def _reachable_groups(w: Workflow) -> set[str]:
    """Group names reachable from top-level `blocks`, directly or transitively through the
    body of another reachable group. A group nobody ever calls can never actually alias
    anything at runtime, so `_check_group_reuse` must not count group_refs that live only
    inside one (design 2026-07-20 §2.2, §6)."""
    seen: set[str] = set()

    def visit(blocks: list[B.Block]) -> None:
        for _, b in _iter_blocks(blocks, ""):
            if isinstance(b, B.GroupRef) and b.name in w.groups and b.name not in seen:
                seen.add(b.name)
                visit(w.groups[b.name].body)

    visit(w.blocks)
    return seen


def _check_group_reuse(w: Workflow, out: list[Diagnostic]) -> bool:
    """A PLAIN group (no params, no locals) is lazily inlined by expand.py: its body is
    expanded exactly ONCE, eagerly, up front -- independent of how many group_refs later
    point at it. If that frozen body reaches a locals-bearing group_ref, the qualified
    names and hoisted seed it produced are fixed at that single expansion; a second
    reference to the plain group would silently replay the SAME resolved instance a
    second time, with no duplicate-instance error to catch it (unlike a direct,
    non-plain reference, where _open_locals's duplicate-`as` check fires live on every
    call). Confirmed empirically: two references to such a group produce one hoisted
    seed but two executions writing the same qualified names. Rejected here, on the
    authored doc, before expansion (design 2026-07-20 §2.2, §6).

    Scope: counts direct textual group_ref occurrences (weighted by enclosing for_each row
    counts) that live in `blocks` or in the body of a group REACHABLE from `blocks` --
    reachability is traversed through plain and parametrized intermediates alike, at any
    depth (fixed 2026-07-20: this previously stopped at the first parametrized hop, and
    separately counted refs inside groups nobody ever calls). It is NOT further multiplied
    through an ENCLOSING group that is itself referenced more than once -- e.g. a plain
    `wash` referenced once inside a PARAMETRIZED `svc`, with `svc` itself referenced twice,
    is not flagged, even though `svc`'s two calls replay `wash`'s single frozen expansion
    twice. That deeper chain needs call-graph multiplicity, not just reachability, and the
    diagnostic on the directly-multiply-referenced group is what is actionable today.
    Mutually-exclusive `branch` arms (`then` and `else`) are also both counted even though
    only one ever runs at a time -- conservative but safe, since correcting it needs path
    analysis this check does not do.
    """
    before = len(out)
    reachable = _reachable_groups(w)
    for name, group in w.groups.items():
        if not _is_plain(group) or not _group_reaches_locals_ref(w, name, set()):
            continue
        count = _ref_count(w.blocks, name, 1)
        for other_name, other in w.groups.items():
            if other_name != name and other_name in reachable:
                count += _ref_count(other.body, name, 1)
        if count > 1:
            out.append(Diagnostic(
                "group", f"groups[{name!r}]",
                f"plain group {name!r} is referenced {count} times, but its body resolves "
                f"a group-local instance; a param-less group's body is expanded once and "
                f"reused verbatim, so every reference beyond the first would alias the "
                f"same instance. Give {name!r} params so each call gets its own expansion, "
                f"or reference it exactly once (design 2026-07-20 §2.2, §6)",
            ))
    return len(out) == before


def _uses_macros(w: Workflow) -> bool:
    # `locals` alone (no `params`) still needs expansion: the body's `{name}` holes are
    # qualified names (design 2026-07-20 §2.2), not substituted by anything the legacy,
    # expansion-free path does.
    if any(g.params or g.locals for g in w.groups.values()):
        return True
    for _, b in _iter_all_blocks(w):
        if isinstance(b, B.ForEach):
            return True
        if isinstance(b, B.GroupRef) and b.args:
            return True
    return False


def _value_matches(kind: str, value: object) -> bool:
    """JSON type agreement for a value kind (design 2026-07-20 §2). `bool` is checked
    before `int` throughout: in Python `True` IS an `int`, and an author who wrote
    `true` in an int slot made a real mistake."""
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "string":
        return isinstance(value, str)
    if isinstance(value, bool):
        return False
    if kind == "int":
        return isinstance(value, int)
    return isinstance(value, (int, float))


# One representative value per value kind, used to derive hole-kind agreement FROM
# `_value_matches` itself (below) rather than hand-writing a second, driftable rule.
_VALUE_KIND_SAMPLES: dict[str, tuple[object, ...]] = {
    "bool": (True, False),
    "string": ("",),
    "int": (0, 1, -1),
    "number": (0, 1, 0.5),
}


def _hole_kind_binds(inner: ParamDecl, decl: ParamDecl) -> bool:
    """May a `{name}` hole declared `inner` (a group param or for_each var) bind a slot
    declared `decl` (design 2026-07-20 §3)? Reference kinds (role/stream/binding) never
    widen -- a reference names one specific thing, not a value with a shape -- and `role`
    additionally requires equal `device_type`. A value kind widens exactly as far as
    `_value_matches` already accepts the equivalent literal in the same slot: every sample
    value of `inner`'s kind must be `_value_matches`-legal for `decl`'s kind, e.g. `int`'s
    samples are all accepted where `number` is declared (an int IS a number), but not
    where `string` or `int` alone (a `number` sample like `0.5` fails) is declared."""
    if decl.kind in REFERENCE_KINDS or inner.kind in REFERENCE_KINDS:
        return inner.kind == decl.kind and inner.device_type == decl.device_type
    return all(_value_matches(decl.kind, v) for v in _VALUE_KIND_SAMPLES[inner.kind])


def _check_role_arg(
    decl: ParamDecl, value: str, ctx: str, w: Workflow, out: list[Diagnostic]
) -> None:
    role = w.roles.get(value)
    if role is None:
        out.append(Diagnostic(
            "declaration", ctx, f"role argument names undeclared role {value!r}"
        ))
    elif role.type != decl.device_type:
        out.append(Diagnostic(
            "declaration", ctx,
            f"role {value!r} has type {role.type!r}, but parameter {decl.name!r} "
            f"requires {decl.device_type!r}",
        ))


def _check_stream_arg(value: str, ctx: str, w: Workflow, out: list[Diagnostic]) -> None:
    if value not in w.streams:
        out.append(Diagnostic(
            "declaration", ctx, f"stream argument names undeclared stream {value!r}"
        ))


def _check_binding_arg(value: str, ctx: str, w: Workflow, out: list[Diagnostic]) -> None:
    """Bindings have no declaration section -- they are created by their writer
    (`compute.into`, `operator_input.name`), so shape and namespace disjointness are
    the only checks available (design 2026-07-20 §2). Existence stays the job of the
    path-sensitive 'may be read before it is written' rule."""
    if _IDENT_RE.fullmatch(value) is None or value in _RESERVED_NAMES:
        out.append(Diagnostic(
            "params", ctx, f"binding argument {value!r} is not a usable binding name"
        ))
    elif value in w.streams:
        out.append(Diagnostic(
            "declaration", ctx,
            f"binding argument {value!r} is already declared as a stream; a name is a "
            f"binding or a stream, never both",
        ))


def _kind_text(decl: ParamDecl) -> str:
    return f"role<{decl.device_type}>" if decl.kind == "role" else decl.kind


def _check_typed_arg(
    decl: ParamDecl,
    value: object,
    ctx: str,
    w: Workflow,
    env: Mapping[str, ParamDecl],
    out: list[Diagnostic],
) -> None:
    """One `group_ref` arg or one `for_each` cell against its declaration. Reference
    kinds resolve against the DECLARED sections only -- see the scope note above."""
    if isinstance(value, str):
        whole = _WHOLE_HOLE_RE.fullmatch(value)
        if whole is not None:
            inner = env.get(whole.group(1))
            if inner is None:
                return  # bound by nothing in scope: the residual-hole scan is the backstop
            if not _hole_kind_binds(inner, decl):
                out.append(Diagnostic(
                    "params", ctx,
                    f"{_kind_text(inner)} variable {inner.name!r} cannot bind a "
                    f"{_kind_text(decl)} parameter",
                ))
            return
        if decl.kind in REFERENCE_KINDS and _HOLE_RE.search(value) is not None:
            out.append(Diagnostic(
                "params", ctx,
                f"{decl.kind} argument {value!r} embeds a hole; a reference argument must "
                f"be a whole name or a whole hole (design 2026-07-20 §3)",
            ))
            return
    if decl.kind in REFERENCE_KINDS:
        if not isinstance(value, str):
            out.append(Diagnostic(
                "params", ctx,
                f"{decl.kind} argument must be a name string, got {value!r}",
            ))
            return
        if decl.kind == "role":
            _check_role_arg(decl, value, ctx, w, out)
        elif decl.kind == "stream":
            _check_stream_arg(value, ctx, w, out)
        else:
            _check_binding_arg(value, ctx, w, out)
        return
    if not _value_matches(decl.kind, value):
        out.append(Diagnostic(
            "params", ctx, f"expected {decl.kind} for parameter {decl.name!r}, got {value!r}"
        ))


def _check_group_args(
    b: B.GroupRef,
    path: str,
    w: Workflow,
    env: Mapping[str, ParamDecl],
    out: list[Diagnostic],
) -> None:
    """`args` must supply EXACTLY the declared params, reported one diagnostic per
    param (design 2026-07-20 §2.4). A set-difference message tells the author what the
    two sets are; a per-param message tells them what to type."""
    group = w.groups.get(b.name)
    if group is None:
        return  # unknown group: already diagnosed by _check_groups
    declared = {p.name: p for p in group.params}
    for name, decl in declared.items():
        if name not in b.args:
            out.append(Diagnostic(
                "group", path,
                f"group_ref {b.name!r} is missing argument {name!r} ({decl.kind})",
            ))
        else:
            _check_typed_arg(decl, b.args[name], f"{path} arg {name!r}", w, env, out)
    for name in b.args:
        if name not in declared:
            out.append(Diagnostic(
                "group", path, f"group_ref {b.name!r} has no parameter {name!r}"
            ))


def _check_for_each(
    b: B.ForEach,
    path: str,
    w: Workflow,
    env: Mapping[str, ParamDecl],
    out: list[Diagnostic],
) -> None:
    for key, present in (("retry", b.retry is not None), ("on_error", b.on_error != "fail"),
                         ("gap_after", b.gap_after is not None),
                         ("start_offset", b.start_offset is not None)):
        if present:
            out.append(Diagnostic(
                "for_each", path,
                f"for_each may not carry block-level {key!r}; put it on the body blocks",
            ))
    if not b.body:
        out.append(Diagnostic("for_each", path, "for_each 'body' must be non-empty"))
    if not b.items:
        out.append(Diagnostic("for_each", path, "for_each 'in' must be non-empty"))
    if not b.vars:
        out.append(Diagnostic("for_each", path, "for_each 'vars' must be non-empty"))
    declared = {v.name: v for v in b.vars}
    for r, row in enumerate(b.items):
        if not isinstance(row, dict):
            out.append(Diagnostic(
                "for_each", path,
                f"for_each 'in' row {r} must be an object mapping every declared var to a "
                f"value, got {row!r}",
            ))
            continue
        for name in declared:
            if name not in row:
                out.append(Diagnostic(
                    "for_each", path, f"for_each 'in' row {r} is missing {name!r}"
                ))
        for name in row:
            if name not in declared:
                out.append(Diagnostic(
                    "for_each", path, f"for_each 'in' row {r} has no variable {name!r}"
                ))
        for name, decl in declared.items():
            if name in row:
                _check_typed_arg(
                    decl, row[name], f"{path} in[{r}] {name!r}", w, env, out
                )


def _check_decl_names(
    decls: list[ParamDecl],
    locals_: Mapping[str, LocalDecl],
    where: str,
    env: Mapping[str, ParamDecl],
    out: list[Diagnostic],
) -> dict[str, ParamDecl]:
    """One binder's names (design 2026-07-20 §2.4). Params and locals share ONE
    namespace: both become `{name}` holes in the same body, so a collision has no
    meaningful resolution. Returns the names this binder introduces."""
    introduced: dict[str, ParamDecl] = {}
    for decl in decls:
        if _IDENT_RE.fullmatch(decl.name) is None:
            out.append(Diagnostic(
                "declaration", where, f"declared name {decl.name!r} is not an identifier"
            ))
        elif decl.name in _RESERVED_NAMES:
            out.append(Diagnostic(
                "declaration", where, f"declared name {decl.name!r} is reserved"
            ))
        if decl.name in introduced:
            out.append(Diagnostic(
                "declaration", where, f"duplicate parameter name {decl.name!r}"
            ))
        introduced[decl.name] = decl
    for name, local in locals_.items():
        if _IDENT_RE.fullmatch(name) is None:
            out.append(Diagnostic(
                "declaration", where, f"declared name {name!r} is not an identifier"
            ))
        elif name in _RESERVED_NAMES:
            out.append(Diagnostic(
                "declaration", where, f"declared name {name!r} is reserved"
            ))
        if name in introduced:
            out.append(Diagnostic(
                "declaration", where,
                f"{name!r} is declared as both a parameter and a local; params and locals "
                f"share one namespace (design 2026-07-20 §2.4)",
            ))
        introduced[name] = ParamDecl(name=name, kind=local.kind)
    for name in introduced:
        if name in env:
            out.append(Diagnostic(
                "declaration", where,
                f"{name!r} shadows an enclosing group parameter or for_each variable of the "
                f"same name; the outer binding substitutes first and the inner one never "
                f"takes effect (design 2026-07-20 §2.4)",
            ))
    return introduced


def _walk_decls(
    blocks: list[B.Block],
    prefix: str,
    w: Workflow,
    env: dict[str, ParamDecl],
    out: list[Diagnostic],
) -> None:
    """Walk the AUTHORED tree carrying the declarations in scope. `_iter_all_blocks`
    cannot serve here: it is scope-blind, and every check below is about what a name
    means at the point it is written."""
    for i, b in enumerate(blocks):
        path = f"{prefix}[{i}]"
        if isinstance(b, B.ForEach):
            _check_for_each(b, path, w, env, out)
            inner = dict(env)
            inner.update(_check_decl_names(b.vars, {}, path, env, out))
            _walk_decls(b.body, f"{path}.body", w, inner, out)
            continue
        if isinstance(b, B.GroupRef):
            _check_group_args(b, path, w, env, out)
        if isinstance(b, (B.Serial, B.Parallel)):
            _walk_decls(b.children, f"{path}.children", w, env, out)
        elif isinstance(b, B.Loop):
            _walk_decls(b.body, f"{path}.body", w, env, out)
        elif isinstance(b, B.Branch):
            _walk_decls(b.then, f"{path}.then", w, env, out)
            if b.else_ is not None:
                _walk_decls(b.else_, f"{path}.else", w, env, out)


def _check_local_init(
    name: str, local: LocalDecl, where: str, out: list[Diagnostic]
) -> None:
    """`init` must be a CONSTANT expression: literals and operators over them, with no
    stat calls, no stream references and no binding references (design 2026-07-20 §2.3).
    The initializer is hoisted ahead of every block in the document, so any data
    dependency it could express is guaranteed unwritten when it runs.

    Task 5's parser already rejects `init` on a stream-kinded local, so only the
    binding case reaches here. Its expression syntax is ALSO already checked at load
    time by serialize._local_decls's `_checked_expr` (unless it embeds a hole), so the
    ExpressionError branch below is defense-in-depth for a LocalDecl built directly
    through the Python API -- not reachable via workflow_from_dict for a hole-free
    `init`, mirroring _check_for_each's row-must-be-an-object check."""
    if local.init is None:
        return
    try:
        expr = parse_expression(local.init)
    except ExpressionError as exc:
        out.append(Diagnostic("declaration", where, f"invalid init expression: {exc}"))
        return
    refs = references(expr)
    named = sorted(refs.bindings | refs.streams_windowed | refs.streams_counted)
    if named:
        reads = ", ".join(repr(n) for n in named)
        out.append(Diagnostic(
            "declaration", where,
            f"local {name!r} init must be a constant expression, but reads {reads}; the "
            f"initializer is hoisted ahead of every block, so nothing it could read is "
            f"written yet (design 2026-07-20 §2.3)",
        ))


def _check_declarations(w: Workflow, out: list[Diagnostic]) -> bool:
    """Every typed-declaration rule, on the authored doc (design 2026-07-20 §2, §4).
    True iff nothing new was found, i.e. the doc is safe to hand to the expander."""
    before = len(out)
    _walk_decls(w.blocks, "blocks", w, {}, out)
    for name, group in w.groups.items():
        where = f"groups[{name!r}]"
        env = _check_decl_names(group.params, group.locals, where, {}, out)
        for local_name, local in group.locals.items():
            _check_local_init(
                local_name, local, f"{where}.locals[{local_name!r}]", out
            )
        _walk_decls(group.body, f"{where}.body", w, env, out)
    return len(out) == before


_INPUT_TYPES: dict[str, BindingType] = {
    "float": "number",
    "int": "number",
    "bool": "bool",
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
    if report.type != "unknown" and not assignable(report.type, expected):
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
        expected: ExprType = "bool" if spec.kind == "bool" else "number"
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


def _role_type(w: Workflow, device: str) -> str | None:
    """Declared device type behind a `device:` field (design 2026-07-20 §5.2), or None when
    it cannot be known here: an unexpanded `{hole}` is not a role name yet, and an undeclared
    role is diagnosed once by `_check_action` rather than by every analysis that walks past
    it. A role name is not a device id and was never decodable into one."""
    decl = w.roles.get(device)
    return None if decl is None else decl.type


def _check_action(
    b: B.Command | B.Measure,
    path: str,
    w: Workflow,
    binding_types: Mapping[str, BindingType],
    out: list[Diagnostic],
) -> None:
    dtype = _role_type(w, b.device)
    if dtype is None:
        if "{" not in b.device:  # a hole defers; a name that is not a role never resolves
            out.append(Diagnostic(
                "declaration", path,
                f"device {b.device!r} is not a declared role; declare it under the "
                f"workflow's 'roles' section. Declared roles: {sorted(w.roles)}",
            ))
        return
    try:
        trait = lookup(dtype, b.verb)
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
_HOLE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_WHOLE_HOLE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}\Z")


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
    _check_expr_type(text, "bool", ctx, binding_types, out)
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
    dtype = _role_type(w, b.device)
    if dtype is None:
        return  # already diagnosed by _check_action
    try:
        trait = lookup(dtype, b.verb)
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


def _check_retry(block: B.Block, path: str, w: Workflow, out: list[Diagnostic]) -> None:
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
    dtype = _role_type(w, block.device)
    if dtype is None:
        return  # already diagnosed by _check_action
    try:
        trait = lookup(dtype, block.verb)
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
    _check_retry(block, path, w, out)
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
    dtype = _role_type(c.workflow, b.device)
    if dtype is None:
        return  # already diagnosed globally; nothing to analyze against
    try:
        trait = lookup(dtype, b.verb)
    except UnknownVerbError:
        return  # already diagnosed globally; nothing to analyze against
    specs = {s.name: s for s in trait.params}
    for name, value in b.params.items():
        spec = specs.get(name)
        if spec is not None and spec.kind != "string":
            _expr_reads(value, f"{path} param {name!r}", state, c)
    action = mode_action(dtype, b.verb, b.params)
    if action is not None and action.kind == "close":
        # A matching close is always legal: closes if open, no-ops if not (design §12).
        state.modes.pop((b.device, action.mode_verb), None)
    else:
        for (device, mode_verb), status in sorted(state.modes.items()):
            if device != b.device:
                continue
            if lookup(dtype, mode_verb).channels & trait.channels:
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
            dtype = _role_type(w, b.device)
            if dtype is None:
                continue
            try:
                trait = lookup(dtype, b.verb)
            except UnknownVerbError:
                continue
            # Keyed by ROLE NAME, not by device id. Injectivity (design §5.4) makes the two
            # intersections provably equivalent; the role name is what the author wrote.
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
    reach the concrete checks — only `_check_groups`, `_check_group_reuse` and
    `_check_declarations` see them; `_validate_workflow` below only ever sees the
    macro-free `expanded` doc."""
    expandable = _check_groups(workflow, out)
    if expandable:  # _check_group_reuse walks the group graph; only sound once acyclic
        expandable = _check_group_reuse(workflow, out) and expandable
    expandable = _check_declarations(workflow, out) and expandable
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
