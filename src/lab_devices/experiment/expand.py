"""for_each / parametrized-group expansion (design 2026-07-15 §4)."""

from __future__ import annotations

import copy
import re
from typing import Any

from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.serialize import (
    _BLOCK_KEYS,
    workflow_from_dict,
    workflow_to_dict,
)
from lab_devices.experiment.workflow import Workflow

_HOLE_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
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


def _interpolate(text: str, env: dict[str, Any]) -> str:
    def sub(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in env:
            return m.group(0)  # leave for an outer for_each/args pass, or the residual scan
        return _fmt(env[name])

    return _HOLE_RE.sub(sub, text)


def _substitute(node: Any, env: dict[str, Any]) -> Any:
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


class _Counter:
    def __init__(self) -> None:
        self.n = 0

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


def _envs(body: dict[str, Any]) -> list[dict[str, Any]]:
    var = body.get("var")
    raw = body.get("in")
    if not isinstance(raw, list) or not raw:
        raise WorkflowLoadError("for_each 'in' must be a non-empty list")
    out: list[dict[str, Any]] = []
    if var is not None:
        if not isinstance(var, str):
            raise WorkflowLoadError("for_each 'var' must be a string")
        for item in raw:
            if isinstance(item, dict):
                raise WorkflowLoadError("for_each with 'var' requires scalar items")
            out.append({var: item})
        return out
    keyset: set[str] | None = None
    for item in raw:
        if not isinstance(item, dict):
            raise WorkflowLoadError("for_each without 'var' requires object items")
        if keyset is None:
            keyset = set(item)
        elif set(item) != keyset:
            raise WorkflowLoadError("for_each object items must share one key set")
        out.append(dict(item))
    return out


def _expand_blocks(
    blocks: list[Any],
    groups: dict[str, Any],
    counter: _Counter,
    depth: int,
    trace: dict[str, str],
    src: str,
    dst: str,
    base: int = 0,
) -> list[Any]:
    out: list[Any] = []
    for i, block in enumerate(blocks):
        out.extend(
            _expand_block(block, groups, counter, depth, trace, f"{src}[{i}]", dst, base + len(out))
        )
    return out


def _expand_block(
    block: Any,
    groups: dict[str, Any],
    counter: _Counter,
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
        return _expand_for_each(block, groups, counter, depth, trace, src, dst, base)
    if key == "group_ref":
        return _expand_group_ref(block, groups, counter, depth, trace, src, dst, base)
    trace[f"{dst}[{base}]"] = src
    body = block[key]
    if isinstance(body, dict):
        for child_key in _CHILD_LISTS.get(key, ()):
            children = body.get(child_key)
            if isinstance(children, list):
                body[child_key] = _expand_blocks(
                    children, groups, counter, depth, trace,
                    f"{src}.{child_key}", f"{dst}[{base}].{child_key}",
                )
    return [block]


def _expand_for_each(
    block: dict[str, Any],
    groups: dict[str, Any],
    counter: _Counter,
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
                substituted, groups, counter, depth + 1, trace,
                f"{src}.body", dst, base + len(out),
            )
        )
    counter.bump(len(out))
    return out


def _expand_group_ref(
    block: dict[str, Any],
    groups: dict[str, Any],
    counter: _Counter,
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
    params = list(group.get("params", [])) if isinstance(group, dict) else []
    if not params and not args:
        trace[f"{dst}[{base}]"] = src
        return [block]  # plain group_ref: preserve the node (lazy inline)
    if group is None:
        raise WorkflowLoadError(f"group_ref {name!r}: unknown group")
    if set(args) != set(params):
        raise WorkflowLoadError(
            f"group_ref {name!r}: args {sorted(args)} must match params {sorted(params)}"
        )
    raw_body = group.get("body", [])
    if not isinstance(raw_body, list):
        raise WorkflowLoadError(f"group {name!r} body must be a list")
    substituted = [_substitute(b, dict(args)) for b in raw_body]
    trace[f"{dst}[{base}]"] = src
    inlined = _expand_blocks(
        substituted, groups, counter, depth + 1, trace,
        f"groups[{name!r}].body", f"{dst}[{base}].children",
    )
    wrapper: dict[str, Any] = {"serial": {"children": inlined}}
    for k in _BLOCK_KEYS:
        if k in block:
            wrapper[k] = copy.deepcopy(block[k])
    counter.bump(1)
    return [wrapper]


def expand_dict(workflow_dict: dict[str, Any]) -> dict[str, Any]:
    """Splice for_each, inline parametrized group_refs, interpolate holes. Pure JSON."""
    return expand_dict_traced(workflow_dict)[0]


def expand_dict_traced(workflow_dict: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """expand_dict plus a source map: expanded structural path -> authored structural path.

    Studio validates the EXPANDED workflow, so its diagnostics carry expanded indices that do
    not match the authored tree; the map is what lets the builder resolve a diagnostic back to
    the block the author can actually edit (design 2026-07-16 §5.3). Many-to-one by nature:
    every for_each copy traces to the one authored body block.
    """
    out = copy.deepcopy(workflow_dict)
    groups = out.get("groups")
    groups = groups if isinstance(groups, dict) else {}
    counter = _Counter()
    trace: dict[str, str] = {}
    for name, g in groups.items():  # expand for_each inside plain-group bodies (used lazily)
        if isinstance(g, dict) and not g.get("params") and isinstance(g.get("body"), list):
            path = f"groups[{name!r}].body"
            g["body"] = _expand_blocks(g["body"], groups, counter, 0, trace, path, path)
    blocks = out.get("blocks")
    if isinstance(blocks, list):
        out["blocks"] = _expand_blocks(blocks, groups, counter, 0, trace, "blocks", "blocks")
    kept = {n: g for n, g in groups.items()
            if not (isinstance(g, dict) and g.get("params"))}
    if kept:
        out["groups"] = kept
    else:
        out.pop("groups", None)
    if counter.n > 0:
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
