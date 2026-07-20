"""Pure-JSON <-> AST (de)serialization. See design §15."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from lab_devices.experiment import blocks as B
from lab_devices.experiment.durations import parse_duration
from lab_devices.experiment.errors import ExpressionError, WorkflowLoadError
from lab_devices.experiment.expr import parse_expression
from lab_devices.experiment.registry import lookup
from lab_devices.experiment.workflow import (
    Defaults,
    Group,
    Metadata,
    ParamDecl,
    Persistence,
    StreamDecl,
    Workflow,
)

SCHEMA_VERSION = 1
_BLOCK_KEYS = ("label", "gap_after", "start_offset", "retry", "on_error")
_DEFAULTS_KEYS = ("retry",)


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


def _checked_expr(value: Any, ctx: str) -> str:
    # A for_each/group-arg hole: the expression grammar never uses '{' (design §3), so this
    # parses only after substitution — mirrors the device-lookup skip in _command/_measure.
    text = _str(value, ctx)
    if "{" in text:
        return text
    try:
        parse_expression(text)
    except ExpressionError as exc:
        raise ExpressionError(f"{ctx}: {exc}") from exc
    return text


def _value(value: Any, ctx: str) -> B.ValueExpr:
    """A scalar slot: a string is an expression (checked now), a number/bool is a literal."""
    if isinstance(value, str):
        return _checked_expr(value, ctx)
    if isinstance(value, bool) or isinstance(value, (int, float)):
        return value
    raise WorkflowLoadError(
        f"{ctx} must be a number, boolean, or expression string, got {value!r}"
    )


def _checked_duration(value: Any, ctx: str) -> str:
    text = _str(value, ctx)
    try:
        parse_duration(text)
    except ValueError as exc:
        raise WorkflowLoadError(f"{ctx}: {exc}") from exc
    return text


def _checked_params(body: Any, ctx: str) -> dict[str, Any]:
    params = _params(body, ctx)
    for name, value in params.items():
        if isinstance(value, str):
            _checked_expr(value, f"{ctx} param {name!r}")
    return params


def _retry(value: Any, ctx: str) -> B.Retry:
    body = _obj(value, ctx)
    attempts = body.get("attempts")
    if not isinstance(attempts, int) or isinstance(attempts, bool) or attempts < 1:
        raise WorkflowLoadError(f"{ctx}: attempts must be an integer >= 1, got {attempts!r}")
    backoff = _checked_duration(body.get("backoff", "1s"), f"{ctx} backoff")
    allow_repeat = body.get("allow_repeat", False)
    if not isinstance(allow_repeat, bool):
        raise WorkflowLoadError(f"{ctx}: allow_repeat must be a boolean, got {allow_repeat!r}")
    return B.Retry(attempts=attempts, backoff=backoff, allow_repeat=allow_repeat)


def _no_misplaced_block_keys(body: Any, ctx: str) -> None:
    """`retry` and `on_error` are siblings of the body, not members of it. Nested, they would
    be silently dropped — the author would believe they had a retry policy and have none.
    Checked for EVERY block type (from block_from_dict): `on_error` is legal on all of them,
    so the trap is too. No block body uses either word as a legitimate field name."""
    if not isinstance(body, dict):
        return
    for key in ("retry", "on_error"):
        if key in body:
            raise WorkflowLoadError(
                f"{ctx}: {key!r} is a block-level key, not a {ctx} body key. Write "
                f'{{"{ctx}": {{...}}, "{key}": ...}}, not {{"{ctx}": {{..., "{key}": ...}}}}'
            )


def _command(body: Any, timing: dict[str, Any]) -> B.Block:
    device = _str(_req(body, "device", "command"), "command device")
    verb = _req(body, "verb", "command")
    if "{" not in device:
        lookup(device, verb)
    return B.Command(device=device, verb=verb, params=_checked_params(body, "command"), **timing)


def _measure(body: Any, timing: dict[str, Any]) -> B.Block:
    device = _str(_req(body, "device", "measure"), "measure device")
    verb = body.get("verb", "measure")
    if "{" not in device:
        lookup(device, verb)
    return B.Measure(
        device=device, verb=verb, into=_req(body, "into", "measure"),
        params=_checked_params(body, "measure"), **timing,
    )


def _compute(body: Any, timing: dict[str, Any]) -> B.Block:
    into = _str(_req(body, "into", "compute"), "compute into")
    value = _value(_req(body, "value", "compute"), "compute value")
    return B.Compute(into=into, value=value, **timing)


def _record(body: Any, timing: dict[str, Any]) -> B.Block:
    into = _str(_req(body, "into", "record"), "record into")
    value = _value(_req(body, "value", "record"), "record value")
    return B.Record(into=into, value=value, **timing)


def _abort(body: Any, timing: dict[str, Any]) -> B.Block:
    if_ = _checked_expr(_req(body, "if", "abort"), "abort if")
    message = _str(_req(body, "message", "abort"), "abort message")
    return B.Abort(if_=if_, message=message, **timing)


def _alarm(body: Any, timing: dict[str, Any]) -> B.Block:
    if_ = _checked_expr(_req(body, "if", "alarm"), "alarm if")
    message = _str(_req(body, "message", "alarm"), "alarm message")
    return B.Alarm(if_=if_, message=message, **timing)


def _operator_input(body: Any, timing: dict[str, Any]) -> B.Block:
    return B.OperatorInput(
        name=_req(body, "name", "operator_input"),
        type=_req(body, "type", "operator_input"),
        prompt=body.get("prompt"), min=body.get("min"), max=body.get("max"),
        choices=body.get("choices"), **timing,
    )


def _wait(body: Any, timing: dict[str, Any]) -> B.Block:
    duration = _checked_duration(_req(body, "duration", "wait"), "wait duration")
    return B.Wait(duration=duration, **timing)


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
    until = _checked_expr(body["until"], "loop until") if has_until else None
    pace = body.get("pace")
    if pace is not None:
        pace = _checked_duration(pace, "loop pace")
    return B.Loop(
        body=_children(_req(body, "body", "loop"), "loop.body"),
        count=body.get("count"), pace=pace,
        until=until, check=check, **timing,
    )


def _branch(body: Any, timing: dict[str, Any]) -> B.Block:
    if_ = _checked_expr(_req(body, "if", "branch"), "branch if")
    then = _children(_req(body, "then", "branch"), "branch.then")
    else_ = _children(body["else"], "branch.else") if "else" in body else None
    return B.Branch(if_=if_, then=then, else_=else_, **timing)


def _group_ref(body: Any, timing: dict[str, Any]) -> B.Block:
    if not isinstance(body, dict):
        raise WorkflowLoadError("group_ref requires an object body")
    args = body.get("args", {})
    if not isinstance(args, dict):
        raise WorkflowLoadError("group_ref args must be an object")
    return B.GroupRef(name=_req(body, "name", "group_ref"), args=dict(args), **timing)


def _for_each(body: Any, timing: dict[str, Any]) -> B.Block:
    if not isinstance(body, dict):
        raise WorkflowLoadError("for_each requires an object body")
    items = _req(body, "in", "for_each")
    if not isinstance(items, list):
        raise WorkflowLoadError("for_each 'in' must be a list")
    children = _children(_req(body, "body", "for_each"), "for_each.body")
    var = body.get("var")
    if var is not None and not isinstance(var, str):
        raise WorkflowLoadError(f"for_each 'var' must be a string, got {var!r}")
    return B.ForEach(var=var, items=items, body=children, **timing)


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
    "for_each": _for_each,
    "compute": _compute,
    "record": _record,
    "abort": _abort,
    "alarm": _alarm,
}


def block_from_dict(d: Any) -> B.Block:
    if not isinstance(d, dict):
        raise WorkflowLoadError(f"block must be an object, got {type(d).__name__}")
    timing = {k: d[k] for k in _BLOCK_KEYS if k in d}
    if "gap_after" in timing:
        timing["gap_after"] = _checked_duration(timing["gap_after"], "gap_after")
    if "start_offset" in timing:
        timing["start_offset"] = _checked_duration(timing["start_offset"], "start_offset")
    if "retry" in timing:
        timing["retry"] = _retry(timing["retry"], "retry")
    if "on_error" in timing and timing["on_error"] not in B.ON_ERROR_VALUES:
        raise WorkflowLoadError(
            f"on_error must be one of {B.ON_ERROR_VALUES}, got {timing['on_error']!r}"
        )
    type_keys = [k for k in d if k not in _BLOCK_KEYS]
    if len(type_keys) != 1:
        raise WorkflowLoadError(f"block must have exactly one type key, got {type_keys}")
    key = type_keys[0]
    builder = _BUILDERS.get(key)
    if builder is None:
        raise WorkflowLoadError(f"unknown block type {key!r}")
    _no_misplaced_block_keys(d[key], key)
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
        body = {"name": b.name}
        if b.args:
            body["args"] = dict(b.args)
        return "group_ref", body
    if isinstance(b, B.ForEach):
        body = {}
        if b.var is not None:
            body["var"] = b.var
        body["in"] = list(b.items)
        body["body"] = [block_to_dict(c) for c in b.body]
        return "for_each", body
    if isinstance(b, B.Compute):
        return "compute", {"into": b.into, "value": b.value}
    if isinstance(b, B.Record):
        return "record", {"into": b.into, "value": b.value}
    if isinstance(b, B.Abort):
        return "abort", {"if": b.if_, "message": b.message}
    if isinstance(b, B.Alarm):
        return "alarm", {"if": b.if_, "message": b.message}
    raise WorkflowLoadError(f"cannot serialize {type(b).__name__}")


def _retry_to_dict(r: B.Retry) -> dict[str, Any]:
    body: dict[str, Any] = {"attempts": r.attempts, "backoff": r.backoff}
    if r.allow_repeat:
        body["allow_repeat"] = True
    return body


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
    if b.retry is not None:
        out["retry"] = _retry_to_dict(b.retry)
    if b.on_error != "fail":
        out["on_error"] = b.on_error
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
    dd = _obj(d.get("defaults", {}), "defaults")
    for key in dd:
        if key not in _DEFAULTS_KEYS:
            if key == "on_error":
                raise WorkflowLoadError(
                    "defaults.on_error is not allowed: a blanket on_error would silently "
                    "tolerate every failure (e.g. a missed drug injection) instead of just "
                    "the ones an author reviewed block by block; set on_error on the "
                    "individual blocks that should tolerate failure instead"
                )
            raise WorkflowLoadError(f"defaults: unknown key {key!r}")
    defaults = Defaults(
        retry=_retry(dd["retry"], "defaults.retry") if "retry" in dd else None
    )
    streams: dict[str, StreamDecl] = {}
    for name, sv in _obj(d.get("streams", {}), "streams").items():
        s = _obj(sv, f"stream {name!r}")
        streams[name] = StreamDecl(units=s.get("units"), persistence=s.get("persistence"))
    groups: dict[str, Group] = {}
    for name, gv in _obj(d.get("groups", {}), "groups").items():
        g = _obj(gv, f"group {name!r}")
        params = g.get("params", [])
        if not isinstance(params, list) or not all(isinstance(p, str) for p in params):
            raise WorkflowLoadError(f"group {name!r} params must be a list of strings")
        groups[name] = Group(
            name=name, body=_children(g.get("body", []), f"groups.{name}.body"),
            # TRANSITIONAL (Task 1 -> Task 3): v1 params are untyped strings. Task 3
            # replaces this with the typed `params` list parser (design 2026-07-20 §2.1).
            params=[ParamDecl(name=p, kind="string") for p in params],
        )
    return Workflow(
        schema_version=version,
        blocks=_children(d.get("blocks", []), "blocks"),
        metadata=metadata, persistence=persistence, streams=streams, groups=groups,
        defaults=defaults,
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
    if w.defaults.retry is not None:
        out["defaults"] = {"retry": _retry_to_dict(w.defaults.retry)}
    if w.streams:
        out["streams"] = {
            name: {k: v for k, v in (("units", s.units), ("persistence", s.persistence))
                   if v is not None}
            for name, s in w.streams.items()
        }
    if w.groups:
        out["groups"] = {
            # TRANSITIONAL (Task 1 -> Task 3): emits v1 name-only params.
            name: ({"params": [p.name for p in g.params]} if g.params else {})
                  | {"body": [block_to_dict(c) for c in g.body]}
            for name, g in w.groups.items()
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
