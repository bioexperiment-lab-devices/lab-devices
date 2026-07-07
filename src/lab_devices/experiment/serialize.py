"""Pure-JSON <-> AST (de)serialization. See design §15."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import WorkflowLoadError
from lab_devices.experiment.registry import lookup
from lab_devices.experiment.workflow import Group, Metadata, Persistence, StreamDecl, Workflow

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


def _obj(value: Any, ctx: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise WorkflowLoadError(f"{ctx} must be an object")
    return value


def _str(value: Any, ctx: str) -> str:
    if not isinstance(value, str):
        raise WorkflowLoadError(f"{ctx} must be a string")
    return value


def _command(body: Any, timing: dict[str, Any]) -> B.Block:
    device = _str(_req(body, "device", "command"), "command device")
    verb = _req(body, "verb", "command")
    lookup(device, verb)
    return B.Command(device=device, verb=verb, params=_params(body, "command"), **timing)


def _measure(body: Any, timing: dict[str, Any]) -> B.Block:
    device = _str(_req(body, "device", "measure"), "measure device")
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
    has_count = body.get("count") is not None
    has_until = body.get("until") is not None
    if has_count == has_until:
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


def _dump_body(b: B.Block) -> tuple[str, dict[str, Any]]:
    if isinstance(b, B.Command):
        body: dict[str, Any] = {"device": b.device, "verb": b.verb}
        if b.params:
            body["params"] = dict(b.params)
        return "command", body
    if isinstance(b, B.Measure):
        body = {"device": b.device, "verb": b.verb, "into": b.into}
        if b.params:
            body["params"] = dict(b.params)
        return "measure", body
    if isinstance(b, B.OperatorInput):
        body = {"name": b.name, "type": b.type}
        for key in ("prompt", "min", "max", "choices"):
            value = getattr(b, key)
            if value is not None:
                body[key] = value
        return "operator_input", body
    if isinstance(b, B.Wait):
        return "wait", {"duration": b.duration}
    if isinstance(b, B.Serial):
        return "serial", {"children": [block_to_dict(c) for c in b.children]}
    if isinstance(b, B.Parallel):
        return "parallel", {"children": [block_to_dict(c) for c in b.children]}
    if isinstance(b, B.Loop):
        body = {"body": [block_to_dict(c) for c in b.body]}
        if b.count is not None:
            body["count"] = b.count
        if b.pace is not None:
            body["pace"] = b.pace
        if b.until is not None:
            body["until"] = b.until
            body["check"] = b.check
        return "loop", body
    if isinstance(b, B.Branch):
        body = {"if": b.if_, "then": [block_to_dict(c) for c in b.then]}
        if b.else_ is not None:
            body["else"] = [block_to_dict(c) for c in b.else_]
        return "branch", body
    if isinstance(b, B.GroupRef):
        return "group_ref", {"name": b.name}
    raise WorkflowLoadError(f"cannot serialize {type(b).__name__}")


def block_to_dict(b: B.Block) -> dict[str, Any]:
    """Serialize a block to its canonical JSON form."""
    key, body = _dump_body(b)
    out: dict[str, Any] = {key: body}
    if b.label is not None:
        out["label"] = b.label
    if b.gap_after is not None:
        out["gap_after"] = b.gap_after
    if b.start_offset is not None:
        out["start_offset"] = b.start_offset
    return out


def workflow_from_dict(d: Any) -> Workflow:
    if not isinstance(d, dict):
        raise WorkflowLoadError("workflow must be an object")
    version = d.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool) or version != SCHEMA_VERSION:
        raise WorkflowLoadError(
            f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION}"
        )
    md = _obj(d.get("metadata", {}), "metadata")
    metadata = Metadata(
        name=md.get("name"), author=md.get("author"), description=md.get("description")
    )
    pd = _obj(d.get("persistence", {}), "persistence")
    persistence = Persistence(
        default=pd.get("default", "in_memory"), format=pd.get("format", "jsonl")
    )
    streams: dict[str, StreamDecl] = {}
    for name, sv in _obj(d.get("streams", {}), "streams").items():
        s = _obj(sv, f"stream {name!r}")
        streams[name] = StreamDecl(units=s.get("units"), persistence=s.get("persistence"))
    groups: dict[str, Group] = {}
    for name, gv in _obj(d.get("groups", {}), "groups").items():
        g = _obj(gv, f"group {name!r}")
        groups[name] = Group(name=name, body=_children(g.get("body", []), f"groups.{name}.body"))
    return Workflow(
        schema_version=version,
        blocks=_children(d.get("blocks", []), "blocks"),
        metadata=metadata, persistence=persistence, streams=streams, groups=groups,
    )


def workflow_to_dict(w: Workflow) -> dict[str, Any]:
    """Serialize to the canonical JSON form (optional sections omitted when empty;
    defaults normalized)."""
    out: dict[str, Any] = {"schema_version": w.schema_version}
    md = {
        k: v for k, v in (("name", w.metadata.name), ("author", w.metadata.author),
                          ("description", w.metadata.description)) if v is not None
    }
    if md:
        out["metadata"] = md
    out["persistence"] = {"default": w.persistence.default, "format": w.persistence.format}
    if w.streams:
        out["streams"] = {
            name: {k: v for k, v in (("units", s.units), ("persistence", s.persistence))
                   if v is not None}
            for name, s in w.streams.items()
        }
    if w.groups:
        out["groups"] = {
            name: {"body": [block_to_dict(c) for c in g.body]} for name, g in w.groups.items()
        }
    out["blocks"] = [block_to_dict(c) for c in w.blocks]
    return out


def load_workflow(path: str | Path) -> Workflow:
    try:
        data = json.loads(Path(path).read_text())
    except json.JSONDecodeError as exc:
        raise WorkflowLoadError(f"invalid JSON: {exc}") from exc
    return workflow_from_dict(data)


def save_workflow(w: Workflow, path: str | Path) -> None:
    Path(path).write_text(json.dumps(workflow_to_dict(w), indent=2) + "\n")
