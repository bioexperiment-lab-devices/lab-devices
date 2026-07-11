"""Public verb/expression catalog for UI layers. See webapp design §4.4."""

from __future__ import annotations

from typing import TypedDict

from lab_devices.experiment.expr import STAT_FNS
from lab_devices.experiment.registry import _REGISTRY


class ParamEntry(TypedDict):
    name: str
    type: str
    required: bool


class VerbEntry(TypedDict):
    kind: str  # "measure" if the verb records a sample, else "command"
    params: list[ParamEntry]
    result_field: str | None


def verb_catalog() -> dict[str, dict[str, VerbEntry]]:
    """Device type -> verb -> UI-facing entry, derived from the private registry."""
    catalog: dict[str, dict[str, VerbEntry]] = {}
    for (device_type, verb), trait in _REGISTRY.items():
        catalog.setdefault(device_type, {})[verb] = VerbEntry(
            kind="measure" if trait.measurement else "command",
            params=[
                ParamEntry(name=p.name, type=p.kind, required=p.required)
                for p in trait.params
            ],
            result_field=trait.result_field,
        )
    return catalog


def expression_functions() -> dict[str, list[str]]:
    """Stat-function names and window forms the expression language accepts."""
    return {"functions": sorted(STAT_FNS), "windows": ["all", "last_n", "duration"]}
