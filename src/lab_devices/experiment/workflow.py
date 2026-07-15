"""Top-level workflow document. See design §15."""

from __future__ import annotations

from dataclasses import dataclass, field

from lab_devices.experiment.blocks import Block, Retry


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


@dataclass
class Group:
    name: str
    body: list[Block] = field(default_factory=list)
    params: list[str] = field(default_factory=list)


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
    defaults: Defaults = field(default_factory=Defaults)
