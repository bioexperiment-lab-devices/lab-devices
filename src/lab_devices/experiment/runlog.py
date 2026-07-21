"""Run-log events and sinks (in-memory this increment). See design 4-exec §12."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class RunEvent:
    """One observable executor event; timestamps come from the run clock."""

    timestamp: float
    kind: str
    block_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    source_path: str | None = None  # authored structural path (engine source map); None off-block


class RunLogSink(Protocol):
    # Sinks MUST NOT hash or dedupe RunEvents: RunEvent is frozen but carries a mutable
    # dict `data`, so it is unhashable by design (§8 documented-constraint ticket).
    def emit(self, event: RunEvent) -> None: ...


class InMemoryRunLog:
    """Default sink: appends to a list (disk sinks arrive in Increment 5)."""

    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    def emit(self, event: RunEvent) -> None:
        self.events.append(event)
