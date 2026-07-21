"""Top-level workflow document. See design §15; typed declarations design 2026-07-20 §2, §5.1."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from lab_devices.experiment.blocks import Block, Retry
from lab_devices.experiment.errors import UnknownRoleError

ParamKind = Literal["int", "number", "bool", "string", "role", "stream", "binding"]
LocalKind = Literal["stream", "binding"]

VALUE_KINDS: frozenset[str] = frozenset({"int", "number", "bool", "string"})
REFERENCE_KINDS: frozenset[str] = frozenset({"role", "stream", "binding"})


@dataclass
class Metadata:
    name: str | None = None
    author: str | None = None
    description: str | None = None


@dataclass
class Persistence:
    default: str = "in_memory"  # "in_memory" | "disk"
    format: str = "jsonl"  # "jsonl" | "csv"


@dataclass
class StreamDecl:
    units: str | None = None
    persistence: str | None = None  # per-stream override


@dataclass(frozen=True)
class ParamDecl:
    """One typed group param or for_each var (design 2026-07-20 §2.1)."""

    name: str
    kind: ParamKind
    device_type: str | None = None  # required iff kind == "role", forbidden otherwise


@dataclass(frozen=True)
class LocalDecl:
    """A stream or binding a group owns (design 2026-07-20 §2.2)."""

    kind: LocalKind
    init: str | None = None          # constant expression; binding-kind only
    units: str | None = None         # stream-kind only
    persistence: str | None = None   # stream-kind only


@dataclass(frozen=True)
class RoleDecl:
    """A named instrument slot (design 2026-07-20 §5.1)."""

    type: str
    device: str | None = None  # optional direct binding for standalone (non-Studio) use


@dataclass
class Group:
    name: str
    body: list[Block] = field(default_factory=list)
    params: list[ParamDecl] = field(default_factory=list)
    locals: dict[str, LocalDecl] = field(default_factory=dict)


@dataclass
class Defaults:
    """Workflow-wide defaults (design 2026-07-14 §2.4). `retry` only — a blanket
    `on_error` would silently make a missed injection survivable."""

    retry: Retry | None = None


@dataclass
class Workflow:
    schema_version: int
    blocks: list[Block] = field(default_factory=list)
    metadata: Metadata = field(default_factory=Metadata)
    persistence: Persistence = field(default_factory=Persistence)
    streams: dict[str, StreamDecl] = field(default_factory=dict)
    groups: dict[str, Group] = field(default_factory=dict)
    roles: dict[str, RoleDecl] = field(default_factory=dict)
    defaults: Defaults = field(default_factory=Defaults)

    def role_type(self, role: str) -> str:
        """Device type of a declared role (design 2026-07-20 §5.1). The single site every
        type-consuming caller reads, now that registry.device_type is gone."""
        try:
            return self.roles[role].type
        except KeyError:
            raise UnknownRoleError(
                f"undeclared role {role!r}; declared roles: {sorted(self.roles)}"
            ) from None
