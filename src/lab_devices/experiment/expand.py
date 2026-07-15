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
            raise WorkflowLoadError(f"for_each/args hole '{{{name}}}' has no binding")
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
    blocks: list[Any], groups: dict[str, Any], counter: _Counter, depth: int
) -> list[Any]:
    out: list[Any] = []
    for block in blocks:
        out.extend(_expand_block(block, groups, counter, depth))
    return out


def _expand_block(
    block: Any, groups: dict[str, Any], counter: _Counter, depth: int
) -> list[Any]:
    if depth > _MAX_DEPTH:
        raise WorkflowLoadError("for_each/group expansion nested too deeply (recursion?)")
    key = _type_key(block)
    if key is None:
        return [block]  # malformed; workflow_from_dict reports it
    if key == "for_each":
        return _expand_for_each(block, groups, counter, depth)
    if key == "group_ref":
        return _expand_group_ref(block, groups, counter, depth)
    body = block[key]
    if isinstance(body, dict):
        for child_key in _CHILD_LISTS.get(key, ()):
            children = body.get(child_key)
            if isinstance(children, list):
                body[child_key] = _expand_blocks(children, groups, counter, depth)
    return [block]


def _expand_for_each(
    block: dict[str, Any], groups: dict[str, Any], counter: _Counter, depth: int
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
        out.extend(_expand_blocks(substituted, groups, counter, depth + 1))
    counter.bump(len(out))
    return out


def _expand_group_ref(
    block: dict[str, Any], groups: dict[str, Any], counter: _Counter, depth: int
) -> list[Any]:
    body = block["group_ref"]
    if not isinstance(body, dict):
        return [block]
    name = body.get("name")
    raw_args = body.get("args")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    group = groups.get(name) if isinstance(name, str) else None
    params = list(group.get("params", [])) if isinstance(group, dict) else []
    if not params and not args:
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
    inlined = _expand_blocks(substituted, groups, counter, depth + 1)
    wrapper: dict[str, Any] = {"serial": {"children": inlined}}
    for k in _BLOCK_KEYS:
        if k in block:
            wrapper[k] = copy.deepcopy(block[k])
    counter.bump(1)
    return [wrapper]


def expand_dict(workflow_dict: dict[str, Any]) -> dict[str, Any]:
    """Splice for_each, inline parametrized group_refs, interpolate holes. Pure JSON."""
    out = copy.deepcopy(workflow_dict)
    groups = out.get("groups")
    groups = groups if isinstance(groups, dict) else {}
    counter = _Counter()
    for g in groups.values():  # expand for_each inside plain-group bodies (used lazily)
        if isinstance(g, dict) and not g.get("params") and isinstance(g.get("body"), list):
            g["body"] = _expand_blocks(g["body"], groups, counter, 0)
    blocks = out.get("blocks")
    if isinstance(blocks, list):
        out["blocks"] = _expand_blocks(blocks, groups, counter, 0)
    kept = {n: g for n, g in groups.items()
            if not (isinstance(g, dict) and g.get("params"))}
    if kept:
        out["groups"] = kept
    else:
        out.pop("groups", None)
    return out


def expand_workflow(w: Workflow) -> Workflow:
    """AST-level expansion, for validate() and ExperimentRun (concrete-typed ASTs only)."""
    return workflow_from_dict(expand_dict(workflow_to_dict(w)))
