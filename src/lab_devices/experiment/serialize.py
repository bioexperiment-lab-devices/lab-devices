"""Pure-JSON <-> AST (de)serialization. See design §15."""

from __future__ import annotations

from typing import Any, Callable

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.registry import lookup

SCHEMA_VERSION = 1
_TIMING_KEYS = ("label", "gap_after", "start_offset")


def _req(body: Any, key: str, ctx: str) -> Any:
    if not isinstance(body, dict) or key not in body:
        raise WorkflowLoadError(f"{ctx} requires {key!r}")
    return body[key]


def _children(raw: Any, ctx: str) -> list[B.Block]:
    if not isinstance(raw, list):
        raise WorkflowLoadError(f"{ctx} must be a list")
    return [block_from_dict(c) for c in raw]


def _params(body: Any, ctx: str) -> dict[str, Any]:
    raw = body.get("params", {})
    if not isinstance(raw, dict):
        raise WorkflowLoadError(f"{ctx} params must be an object")
    return dict(raw)


def _command(body: Any, timing: dict[str, Any]) -> B.Block:
    device, verb = _req(body, "device", "command"), _req(body, "verb", "command")
    lookup(device, verb)
    return B.Command(device=device, verb=verb, params=_params(body, "command"), **timing)


def _measure(body: Any, timing: dict[str, Any]) -> B.Block:
    device = _req(body, "device", "measure")
    verb = body.get("verb", "measure")
    lookup(device, verb)
    return B.Measure(
        device=device, verb=verb, into=_req(body, "into", "measure"),
        params=_params(body, "measure"), **timing,
    )


def _operator_input(body: Any, timing: dict[str, Any]) -> B.Block:
    return B.OperatorInput(
        name=_req(body, "name", "operator_input"),
        type=_req(body, "type", "operator_input"),
        prompt=body.get("prompt"), min=body.get("min"), max=body.get("max"),
        choices=body.get("choices"), **timing,
    )


def _wait(body: Any, timing: dict[str, Any]) -> B.Block:
    return B.Wait(duration=_req(body, "duration", "wait"), **timing)


def _serial(body: Any, timing: dict[str, Any]) -> B.Block:
    children = _children(_req(body, "children", "serial"), "serial.children")
    return B.Serial(children=children, **timing)


def _parallel(body: Any, timing: dict[str, Any]) -> B.Block:
    return B.Parallel(
        children=_children(_req(body, "children", "parallel"), "parallel.children"), **timing
    )


def _loop(body: Any, timing: dict[str, Any]) -> B.Block:
    if not isinstance(body, dict):
        raise WorkflowLoadError("loop requires an object body")
    if ("count" in body) == ("until" in body):
        raise WorkflowLoadError("loop requires exactly one of 'count' or 'until'")
    check = body.get("check", "after")
    if check not in ("before", "after"):
        raise WorkflowLoadError(f"loop check must be 'before' or 'after', got {check!r}")
    return B.Loop(
        body=_children(_req(body, "body", "loop"), "loop.body"),
        count=body.get("count"), pace=body.get("pace"),
        until=body.get("until"), check=check, **timing,
    )


def _branch(body: Any, timing: dict[str, Any]) -> B.Block:
    if_ = _req(body, "if", "branch")
    then = _children(_req(body, "then", "branch"), "branch.then")
    else_ = _children(body["else"], "branch.else") if "else" in body else None
    return B.Branch(if_=if_, then=then, else_=else_, **timing)


def _group_ref(body: Any, timing: dict[str, Any]) -> B.Block:
    return B.GroupRef(name=_req(body, "name", "group_ref"), **timing)


_BUILDERS: dict[str, Callable[[Any, dict[str, Any]], B.Block]] = {
    "command": _command,
    "measure": _measure,
    "operator_input": _operator_input,
    "wait": _wait,
    "serial": _serial,
    "parallel": _parallel,
    "loop": _loop,
    "branch": _branch,
    "group_ref": _group_ref,
}


def block_from_dict(d: Any) -> B.Block:
    if not isinstance(d, dict):
        raise WorkflowLoadError(f"block must be an object, got {type(d).__name__}")
    timing = {k: d[k] for k in _TIMING_KEYS if k in d}
    type_keys = [k for k in d if k not in _TIMING_KEYS]
    if len(type_keys) != 1:
        raise WorkflowLoadError(f"block must have exactly one type key, got {type_keys}")
    key = type_keys[0]
    builder = _BUILDERS.get(key)
    if builder is None:
        raise WorkflowLoadError(f"unknown block type {key!r}")
    return builder(d[key], timing)
