"""Role -> device-id substitution and doc-level role checks. See webapp design §4.2-4.3."""

from __future__ import annotations

import copy
import re
from typing import Any

ROLE_NAME_RE = re.compile(r"[a-z][a-z0-9_]*\Z")

# Mirrors the engine serializer: block dict = one type key + optional timing keys.
_TIMING_KEYS = ("label", "gap_after", "start_offset")
_DEVICE_BLOCKS = ("command", "measure")
_CHILD_LISTS: dict[str, tuple[str, ...]] = {
    "serial": ("children",),
    "parallel": ("children",),
    "loop": ("body",),
    "branch": ("then", "else"),
}


def _diag(category: str, path: str, message: str) -> dict[str, str]:
    return {"category": category, "path": path, "message": message}


def role_diagnostics(roles: dict[str, str], device_types: set[str]) -> list[dict[str, str]]:
    """Doc-level checks the engine cannot see (§4.3): role-name shape + catalog types."""
    out: list[dict[str, str]] = []
    for name, dtype in roles.items():
        path = f"roles[{name!r}]"
        if not ROLE_NAME_RE.fullmatch(name):
            out.append(_diag("roles", path, f"role name {name!r} must match [a-z][a-z0-9_]*"))
        if dtype not in device_types:
            out.append(_diag("roles", path, f"unknown device type {dtype!r}"))
    return out


def placeholder_ids(roles: dict[str, str]) -> dict[str, str]:
    """Role -> distinct placeholder id whose engine-derived type is the role type (§4.3)."""
    counters: dict[str, int] = {}
    out: dict[str, str] = {}
    for name, dtype in roles.items():
        i = counters.get(dtype, 0)
        counters[dtype] = i + 1
        out[name] = f"{dtype}_{i}"
    return out


def substitute(
    workflow: dict[str, Any], mapping: dict[str, str]
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Deep-copied workflow with every block's `device` role swapped for mapping[role].

    Serves both placeholder substitution (§4.3) and real run substitution (§7.1). Unknown
    roles yield diagnostics at engine-grammar structural paths; malformed nodes are left
    untouched for `workflow_from_dict` to report.
    """
    out = copy.deepcopy(workflow)
    diags: list[dict[str, str]] = []
    blocks = out.get("blocks")
    if isinstance(blocks, list):
        _walk(blocks, "blocks", mapping, diags)
    groups = out.get("groups")
    if isinstance(groups, dict):
        for name, group in groups.items():
            if isinstance(group, dict) and isinstance(group.get("body"), list):
                _walk(group["body"], f"groups[{name!r}].body", mapping, diags)
    return out, diags


def _walk(
    blocks: list[Any], prefix: str, mapping: dict[str, str], diags: list[dict[str, str]]
) -> None:
    for i, block in enumerate(blocks):
        path = f"{prefix}[{i}]"
        if not isinstance(block, dict):
            continue
        type_keys = [k for k in block if k not in _TIMING_KEYS]
        if len(type_keys) != 1:
            continue
        key = type_keys[0]
        body = block[key]
        if not isinstance(body, dict):
            continue
        if key in _DEVICE_BLOCKS:
            device = body.get("device")
            if isinstance(device, str):
                if device in mapping:
                    body["device"] = mapping[device]
                else:
                    diags.append(
                        _diag("roles", path, f"block references unknown role {device!r}")
                    )
        for child_key in _CHILD_LISTS.get(key, ()):
            children = body.get(child_key)
            if isinstance(children, list):
                _walk(children, f"{path}.{child_key}", mapping, diags)
