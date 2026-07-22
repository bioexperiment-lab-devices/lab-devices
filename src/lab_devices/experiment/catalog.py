"""Public verb/expression catalog for UI layers. See webapp design §4.4."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from lab_devices.experiment.expr import STAT_FNS
from lab_devices.experiment.registry import _REGISTRY, ParamSpec


class ParamEntry(TypedDict):
    name: str
    type: str
    required: bool
    values: NotRequired[list[str]]
    default: NotRequired[str | int | bool]
    on_omit: NotRequired[str]


class VerbEntry(TypedDict):
    kind: str  # "measure" if the verb records a sample, else "command"
    params: list[ParamEntry]
    result_field: str | None
    retry_safe: bool  # False = re-issuing is not idempotent; UI disables the retry control


def _param_entry(p: ParamSpec) -> ParamEntry:
    """Serialize one param, emitting `values`/`default`/`on_omit` only when set so a param
    without them keeps its minimal 3-key shape."""
    entry: ParamEntry = {"name": p.name, "type": p.kind, "required": p.required}
    if p.values is not None:
        entry["values"] = list(p.values)
    if p.default is not None:
        entry["default"] = p.default
    if p.on_omit is not None:
        entry["on_omit"] = p.on_omit
    return entry


def verb_catalog() -> dict[str, dict[str, VerbEntry]]:
    """Device type -> verb -> UI-facing entry, derived from the private registry."""
    catalog: dict[str, dict[str, VerbEntry]] = {}
    for (device_type, verb), trait in _REGISTRY.items():
        catalog.setdefault(device_type, {})[verb] = VerbEntry(
            kind="measure" if trait.measurement else "command",
            params=[_param_entry(p) for p in trait.params],
            result_field=trait.result_field,
            retry_safe=trait.retry_safe,
        )
    return catalog


def expression_functions() -> dict[str, list[str]]:
    """Stat-function names and window forms the expression language accepts."""
    return {"functions": sorted(STAT_FNS), "windows": ["all", "last_n", "duration"]}
