"""Lenient dataclass models. Unknown/missing fields never crash parsing; the full
JSON payload is preserved on `.raw`. See spec §7."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, ClassVar, Mapping, Self


@dataclass
class RawModel:
    """Base for all result models. Subclass fields must have defaults."""

    raw: Mapping[str, Any] = field(default_factory=dict, repr=False, kw_only=True)

    # field_name -> (nested model, is_list)
    _NESTED: ClassVar[dict[str, tuple[type["RawModel"], bool]]] = {}

    @classmethod
    def from_raw(cls, data: Mapping[str, Any] | None) -> Self:
        data = data or {}
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name == "raw" or f.name not in data:
                continue
            value = data[f.name]
            nested = cls._NESTED.get(f.name)
            if nested is not None and value is not None:
                model, is_list = nested
                value = (
                    [model.from_raw(v) for v in value]
                    if is_list
                    else model.from_raw(value)
                )
            kwargs[f.name] = value
        return cls(raw=dict(data), **kwargs)


@dataclass
class Range(RawModel):
    min: float | None = None
    max: float | None = None


@dataclass
class Identify(RawModel):
    device_type: str | None = None
    model: str | None = None
    serial: str | None = None
    firmware_version: str | None = None
    protocol_version: str | None = None
    # dict by default; typed devices replace this with a typed capabilities model.
    capabilities: Any = None


@dataclass
class DeviceInfo(RawModel):
    # `_NESTED` is declared before the `type` field below: the field's own annotation
    # would otherwise shadow the builtin `type` name for the rest of this class body
    # (mypy resolves annotations using class-body scope, in source order).
    _NESTED: ClassVar[dict[str, tuple[type[RawModel], bool]]] = {"identify": (Identify, False)}

    id: str | None = None
    type: str | None = None
    port: str | None = None
    connected: bool | None = None
    identify: Identify | None = None


@dataclass
class AgentInfo(RawModel):
    version: str | None = None
    build_sha: str | None = None
    os: str | None = None
    arch: str | None = None
    hostname: str | None = None
    machine_id: str | None = None
    uptime_seconds: int | None = None


@dataclass
class PingResult(RawModel):
    uptime_ms: int | None = None
