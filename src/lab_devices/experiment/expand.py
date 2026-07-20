"""for_each / parametrized-group expansion (design 2026-07-15 §4, 2026-07-20 §3)."""

from __future__ import annotations

import copy
import re
from typing import Any, cast

from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.serialize import (
    _BLOCK_KEYS,
    workflow_from_dict,
    workflow_to_dict,
)
from lab_devices.experiment.workflow import REFERENCE_KINDS, VALUE_KINDS, Workflow

# name -> (kind, value). Reference kinds carry the resolved NAME as a str.
Env = dict[str, tuple[str, Any]]

_HOLE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
# Mirrors validate.py:256. Not imported: validate.py imports expand.py, so the dependency
# would be circular.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ALL_KINDS = VALUE_KINDS | REFERENCE_KINDS
_EXPANSION_CAP = 10_000
_MAX_DEPTH = 64
_CHILD_LISTS: dict[str, tuple[str, ...]] = {
    "serial": ("children",),
    "parallel": ("children",),
    "loop": ("body",),
    "branch": ("then", "else"),
}
_FOR_EACH_FORBIDDEN = ("retry", "on_error", "gap_after", "start_offset")


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else repr(value)
    return str(value)


def _ident(value: Any) -> bool:
    return isinstance(value, str) and _IDENT_RE.fullmatch(value) is not None


def _kind_ok(kind: str, value: Any) -> bool:
    """JSON type of `value` against `kind` (design 2026-07-20 §2)."""
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    return isinstance(value, str)  # "string" and every reference kind carry a str


def _decls(raw: Any, where: str) -> list[tuple[str, str]]:
    """Read a `params`/`vars` list of ParamDecl objects into ordered (name, kind) pairs.

    expand_dict runs on raw JSON, before workflow_from_dict, so it cannot reuse the
    ParamDecl parsing in serialize.py -- it needs its own tolerant read of the same shape.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise WorkflowLoadError(f"{where} must be a list of declarations")
    out: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise WorkflowLoadError(f"{where} entries must be objects, got {item!r}")
        name, kind = item.get("name"), item.get("kind")
        if not isinstance(name, str) or not isinstance(kind, str) or kind not in _ALL_KINDS:
            raise WorkflowLoadError(f"{where} entry {item!r} needs a 'name' and a valid 'kind'")
        out.append((name, kind))
    return out


def _bind(decls: list[tuple[str, str]], supplied: dict[str, Any], where: str) -> Env:
    """Exact-name match plus a per-cell kind check. Shared by group args and for_each rows.

    Checks missing names before extra names: a call site that both omits a declared
    param and supplies an unrelated one should be told about the declared one it owes,
    not merely that the unrelated one is unwelcome.
    """
    env: Env = {}
    for name, kind in decls:
        if name not in supplied:
            raise WorkflowLoadError(f"{where}: missing {name!r} (kind {kind!r})")
        value = supplied[name]
        if not _kind_ok(kind, value):
            raise WorkflowLoadError(f"{where}: {name!r} expects kind {kind!r}, got {value!r}")
        env[name] = (kind, value)
    declared = [n for n, _ in decls]
    extra = sorted(set(supplied) - set(declared))
    if extra:
        raise WorkflowLoadError(f"{where}: unknown name {extra[0]!r}; declared {declared}")
    return env


_IDENT_CHAR_RE = re.compile(r"[A-Za-z0-9_]")
# Only used by _glued, which only ever runs on reference-kind holes: there, a neighbouring
# "{" or "}" is itself glue (see docstring below), so it joins the identifier-char class.
_IDENT_OR_BRACE_RE = re.compile(r"[A-Za-z0-9_{}]")


def _glued(text: str, m: re.Match[str]) -> bool:
    """True if a hole abuts identifier text, i.e. it would manufacture a name instead of
    referring to a declared one. `count({od}, last=5)` is fine -- `(` and `,` delimit it;
    `od_{od}` and `{od}_raw` are not (design 2026-07-20 §3).

    Only called for reference-kind holes. Adjacency is judged in the AUTHORED text, before
    substitution -- so a neighbouring hole never shows up as an identifier character, it
    shows up as `{` or `}`. Left unhandled, `"{od}{other}"` would pass this check and, after
    both holes are substituted, manufacture `od_1od_2` -- exactly the name-surgery this rule
    exists to forbid. So for this reference-kind check, `{` and `}` count as glue too."""
    before = text[m.start() - 1] if m.start() > 0 else ""
    after = text[m.end()] if m.end() < len(text) else ""
    return bool(_IDENT_OR_BRACE_RE.match(before) or _IDENT_OR_BRACE_RE.match(after))


def _interpolate(text: str, env: Env) -> Any:
    """Substitute holes in one string (design 2026-07-20 §3). May return a non-string."""
    whole = _HOLE_RE.fullmatch(text)
    if whole is not None:
        name = whole.group(1)
        if name not in env:
            return text  # leave for an outer for_each/args pass, or the residual scan
        kind, value = env[name]
        if kind in VALUE_KINDS:
            return value  # typed JSON value: an int stays an int (design §3.1)
        return value  # reference kinds already carry the resolved name as a str

    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in env:
            return m.group(0)  # order-independence: not ours to bind
        kind, value = env[name]
        if kind in REFERENCE_KINDS and _glued(text, m):
            raise WorkflowLoadError(
                f"{kind} param {name!r} may not be concatenated with adjacent identifier text "
                f"in {text!r}: a reference must occupy a whole identifier "
                f"(design 2026-07-20 §3)"
            )
        return _fmt(value)

    return _HOLE_RE.sub(sub, text)


def _substitute(node: Any, env: Env) -> Any:
    """Deep-copy a JSON node, interpolating every string against env."""
    if isinstance(node, str):
        return _interpolate(node, env)
    if isinstance(node, list):
        return [_substitute(x, env) for x in node]
    if isinstance(node, dict):
        return {k: _substitute(v, env) for k, v in node.items()}
    return node


def _residual_hole(node: Any) -> str | None:
    """The first '{name}' hole left in a fully-expanded tree, or None."""
    if isinstance(node, str):
        m = _HOLE_RE.search(node)
        return m.group(0) if m is not None else None
    if isinstance(node, list):
        for x in node:
            found = _residual_hole(x)
            if found is not None:
                return found
    elif isinstance(node, dict):
        for v in node.values():
            found = _residual_hole(v)
            if found is not None:
                return found
    return None


_BLOCKS_INDEX_RE = re.compile(r"\Ablocks\[(\d+)\]")


def _shift_block_traces(trace: dict[str, str], k: int) -> dict[str, str]:
    """Re-key top-level `blocks[i]...` entries after k init seeds are prepended.

    Hoisted seeds land at the FRONT of workflow['blocks'] (design 2026-07-20 §2.3), so every
    already-recorded expanded path `blocks[i]` -- and every path nested under it, e.g.
    `blocks[i].children[0]` -- becomes `blocks[i + k]`. Only the FIRST index moves: nesting
    below it is unaffected by a top-level prepend. Keys rooted at `groups['x'].body[...]`
    (the lazy-inline path) do not move at all. Authored paths -- the dict VALUES -- never
    move either: the author wrote no seeds, so nothing in the authored tree shifted.
    """
    if k == 0:
        return trace
    shifted: dict[str, str] = {}
    for key, authored in trace.items():
        m = _BLOCKS_INDEX_RE.match(key)
        if m is None:
            shifted[key] = authored
            continue
        shifted[f"blocks[{int(m.group(1)) + k}]{key[m.end():]}"] = authored
    return shifted


class _Expansion:
    """Mutable expansion state threaded through the recursion."""

    def __init__(self) -> None:
        self.n = 0
        self.seeds: list[tuple[dict[str, Any], str]] = []  # (compute block, authored path)
        self.streams: dict[str, dict[str, Any]] = {}       # qualified name -> StreamDecl JSON
        self.instances: dict[str, str] = {}                # qualified `as` -> claiming group
        self.bindings: set[str] = set()                    # qualified binding names emitted

    def bump(self, k: int) -> None:
        self.n += k
        if self.n > _EXPANSION_CAP:
            raise WorkflowLoadError(
                f"for_each/group expansion exceeds {_EXPANSION_CAP} blocks"
            )


def _type_key(block: Any) -> str | None:
    if not isinstance(block, dict):
        return None
    keys = [k for k in block if k not in _BLOCK_KEYS]
    return keys[0] if len(keys) == 1 else None


def _envs(body: dict[str, Any]) -> list[Env]:
    """One Env per `in` row, bound against the declared `vars` (design 2026-07-20 §4).

    Replaces the untyped check that `in` object items merely shared one key set: rows are now
    checked against a declaration, so a missing or extra key is named rather than inferred.
    """
    if "var" in body:
        raise WorkflowLoadError(
            "for_each 'var' + scalar 'in' shorthand was removed in schema_version 2; declare "
            "'vars': [{'name': ..., 'kind': ...}] and give 'in' object rows "
            "(design 2026-07-20 §4)"
        )
    decls = _decls(body.get("vars"), "for_each 'vars'")
    raw = body.get("in")
    if not isinstance(raw, list) or not raw:
        raise WorkflowLoadError("for_each 'in' must be a non-empty list")
    out: list[Env] = []
    for r, row in enumerate(raw):
        if not isinstance(row, dict):
            raise WorkflowLoadError(f"for_each 'in' row {r} must be an object, got {row!r}")
        out.append(_bind(decls, row, f"for_each 'in' row {r}"))
    return out


def _expand_blocks(
    blocks: list[Any],
    groups: dict[str, Any],
    exp: _Expansion,
    depth: int,
    trace: dict[str, str],
    src: str,
    dst: str,
    base: int = 0,
) -> list[Any]:
    out: list[Any] = []
    for i, block in enumerate(blocks):
        out.extend(
            _expand_block(block, groups, exp, depth, trace, f"{src}[{i}]", dst, base + len(out))
        )
    return out


def _expand_block(
    block: Any,
    groups: dict[str, Any],
    exp: _Expansion,
    depth: int,
    trace: dict[str, str],
    src: str,
    dst: str,
    base: int,
) -> list[Any]:
    if depth > _MAX_DEPTH:
        raise WorkflowLoadError("for_each/group expansion nested too deeply (recursion?)")
    key = _type_key(block)
    if key is None:
        trace[f"{dst}[{base}]"] = src
        return [block]  # malformed; workflow_from_dict reports it
    if key == "for_each":
        return _expand_for_each(block, groups, exp, depth, trace, src, dst, base)
    if key == "group_ref":
        return _expand_group_ref(block, groups, exp, depth, trace, src, dst, base)
    trace[f"{dst}[{base}]"] = src
    body = block[key]
    if isinstance(body, dict):
        for child_key in _CHILD_LISTS.get(key, ()):
            children = body.get(child_key)
            if isinstance(children, list):
                body[child_key] = _expand_blocks(
                    children, groups, exp, depth, trace,
                    f"{src}.{child_key}", f"{dst}[{base}].{child_key}",
                )
    return [block]


def _expand_for_each(
    block: dict[str, Any],
    groups: dict[str, Any],
    exp: _Expansion,
    depth: int,
    trace: dict[str, str],
    src: str,
    dst: str,
    base: int,
) -> list[Any]:
    for k in _FOR_EACH_FORBIDDEN:
        if k in block:
            raise WorkflowLoadError(
                f"for_each may not carry block-level {k!r}; put it on the body blocks"
            )
    body = block["for_each"]
    if not isinstance(body, dict):
        raise WorkflowLoadError("for_each requires an object body")
    tmpl = body.get("body")
    if not isinstance(tmpl, list) or not tmpl:
        raise WorkflowLoadError("for_each 'body' must be a non-empty list")
    out: list[Any] = []
    for env in _envs(body):
        substituted = [_substitute(b, env) for b in tmpl]
        out.extend(
            _expand_blocks(
                substituted, groups, exp, depth + 1, trace,
                f"{src}.body", dst, base + len(out),
            )
        )
    exp.bump(len(out))
    return out


def _open_locals(
    gname: str, locals_: dict[str, Any], as_value: Any, call_env: Env, exp: _Expansion
) -> Env:
    """Qualify one instance's locals as `{as}_{local}`, emitting streams and init seeds.

    `call_env` is the group_ref's bound args env: an `init` expression is restricted to a
    constant expression (design 2026-07-20 §2.3) -- a value-kind param hole is still constant
    after substitution, so it is substituted against the call site before being hoisted.
    """
    if as_value is not None and not _ident(as_value):
        raise WorkflowLoadError(
            f"group_ref {gname!r}: 'as' must expand to an identifier, got {as_value!r} "
            f"(design 2026-07-20 §6)"
        )
    if not locals_:
        return {}  # `as` is optional for a group with nothing to qualify
    if as_value is None:
        raise WorkflowLoadError(
            f"group_ref {gname!r}: 'as' is required because the group declares locals "
            f"(design 2026-07-20 §6)"
        )
    if as_value in exp.instances:
        raise WorkflowLoadError(
            f"group_ref {gname!r}: duplicate instance name {as_value!r}, already used by "
            f"group_ref {exp.instances[as_value]!r} (design 2026-07-20 §6)"
        )
    exp.instances[as_value] = gname
    env: Env = {}
    for lname, decl in locals_.items():
        if not isinstance(decl, dict):
            raise WorkflowLoadError(f"group {gname!r} local {lname!r} must be an object")
        kind = decl.get("kind")
        if kind not in ("stream", "binding"):
            raise WorkflowLoadError(
                f"group {gname!r} local {lname!r}: kind must be 'stream' or 'binding' "
                f"(design 2026-07-20 §2.2)"
            )
        qualified = f"{as_value}_{lname}"
        env[lname] = (kind, qualified)
        if kind == "stream":
            if qualified in exp.streams:
                raise WorkflowLoadError(
                    f"group local emits stream {qualified!r}, which is already emitted "
                    f"(design 2026-07-20 §2.2)"
                )
            exp.streams[qualified] = {
                k: decl[k] for k in ("units", "persistence") if decl.get(k) is not None
            }
        else:
            if qualified in exp.bindings:
                raise WorkflowLoadError(
                    f"group local emits binding {qualified!r}, which is already emitted "
                    f"(design 2026-07-20 §2.2)"
                )
            exp.bindings.add(qualified)
            if decl.get("init") is not None:
                seed_value = _substitute(decl["init"], call_env)
                if not isinstance(seed_value, str):
                    seed_value = _fmt(seed_value)  # compute.value is an expression string
                exp.seeds.append((
                    {"compute": {"into": qualified, "value": seed_value}},
                    f"groups[{gname!r}].locals[{lname!r}]",
                ))
    return env


def _expand_group_ref(
    block: dict[str, Any],
    groups: dict[str, Any],
    exp: _Expansion,
    depth: int,
    trace: dict[str, str],
    src: str,
    dst: str,
    base: int,
) -> list[Any]:
    # Caveat: a group `param` name must not collide with an inner for_each `var` —
    # the param would shadow the loop var (no enforcement here).
    body = block["group_ref"]
    if not isinstance(body, dict):
        trace[f"{dst}[{base}]"] = src
        return [block]
    name = body.get("name")
    raw_args = body.get("args")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    group = groups.get(name) if isinstance(name, str) else None
    gdict: dict[str, Any] = group if isinstance(group, dict) else {}
    decls = _decls(gdict.get("params"), f"group {name!r} params")
    raw_locals = gdict.get("locals")
    locals_: dict[str, Any] = raw_locals if isinstance(raw_locals, dict) else {}
    if not decls and not args and not locals_:
        trace[f"{dst}[{base}]"] = src
        return [block]  # plain group_ref: preserve the node (lazy inline)
    if group is None:
        raise WorkflowLoadError(f"group_ref {name!r}: unknown group")
    # group is non-None only when `name` matched the isinstance(name, str) guard above.
    env = _bind(decls, args, f"group_ref {name!r} args")
    env.update(_open_locals(cast(str, name), locals_, body.get("as"), env, exp))
    raw_body = group.get("body", [])
    if not isinstance(raw_body, list):
        raise WorkflowLoadError(f"group {name!r} body must be a list")
    substituted = [_substitute(b, env) for b in raw_body]
    trace[f"{dst}[{base}]"] = src
    inlined = _expand_blocks(
        substituted, groups, exp, depth + 1, trace,
        f"groups[{name!r}].body", f"{dst}[{base}].children",
    )
    wrapper: dict[str, Any] = {"serial": {"children": inlined}}
    for k in _BLOCK_KEYS:
        if k in block:
            wrapper[k] = copy.deepcopy(block[k])
    exp.bump(1)
    return [wrapper]


def expand_dict(workflow_dict: dict[str, Any]) -> dict[str, Any]:
    """Splice for_each, inline parametrized group_refs, interpolate holes. Pure JSON."""
    return expand_dict_traced(workflow_dict)[0]


def expand_dict_traced(workflow_dict: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """expand_dict plus a source map: expanded structural path -> authored structural path.

    Studio validates the EXPANDED workflow, so its diagnostics carry expanded indices that do
    not match the authored tree; the map is what lets the builder resolve a diagnostic back to
    the block the author can actually edit (design 2026-07-16 §5.3). Many-to-one by nature:
    every for_each copy traces to the one authored body block, and every hoisted init seed
    traces to the `locals` entry that declared it.
    """
    out = copy.deepcopy(workflow_dict)
    groups = out.get("groups")
    groups = groups if isinstance(groups, dict) else {}
    exp = _Expansion()
    trace: dict[str, str] = {}
    for name, g in groups.items():  # expand for_each inside plain-group bodies (used lazily)
        if (isinstance(g, dict) and not g.get("params") and not g.get("locals")
                and isinstance(g.get("body"), list)):
            path = f"groups[{name!r}].body"
            g["body"] = _expand_blocks(g["body"], groups, exp, 0, trace, path, path)
    blocks = out.get("blocks")
    if isinstance(blocks, list):
        out["blocks"] = _expand_blocks(blocks, groups, exp, 0, trace, "blocks", "blocks")
    if exp.seeds:
        # Prepending shifts every expanded top-level index; the trace must move with it.
        trace = _shift_block_traces(trace, len(exp.seeds))
        for j, (_seed, authored) in enumerate(exp.seeds):
            trace[f"blocks[{j}]"] = authored
        out["blocks"] = [seed for seed, _ in exp.seeds] + list(out.get("blocks", []))
    if exp.streams:
        merged = dict(out.get("streams") or {})
        for qname, sdecl in exp.streams.items():
            if qname in merged:
                raise WorkflowLoadError(
                    f"group local emits stream {qname!r}, which is already declared "
                    f"(design 2026-07-20 §2.2)"
                )
            merged[qname] = sdecl
        out["streams"] = merged
    kept = {n: g for n, g in groups.items()
            if not (isinstance(g, dict) and (g.get("params") or g.get("locals")))}
    if kept:
        out["groups"] = kept
    else:
        out.pop("groups", None)
    if exp.n > 0:
        hole = _residual_hole(out.get("blocks", []))
        if hole is None:
            for g in kept.values():
                if isinstance(g, dict):
                    hole = _residual_hole(g.get("body", []))
                    if hole is not None:
                        break
        if hole is not None:
            raise WorkflowLoadError(f"unbound hole '{hole}' remains after expansion")
    return out, trace


def expand_workflow(w: Workflow) -> Workflow:
    """AST-level expansion, for validate() and ExperimentRun (concrete-typed ASTs only)."""
    return workflow_from_dict(expand_dict(workflow_to_dict(w)))
