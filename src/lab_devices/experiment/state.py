"""Runtime data-plane state: streams and operator-input bindings. See design §6."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sample:
    """One stream point; timestamp shares the clock used for the evaluator's `now`."""

    timestamp: float
    value: float


class Stream:
    """Append-only, timestamp-ordered series produced by Measure blocks (design §6)."""

    def __init__(self) -> None:
        self._samples: list[Sample] = []

    def append(self, timestamp: float, value: float) -> None:
        if self._samples and timestamp < self._samples[-1].timestamp:
            raise ValueError(
                f"stream timestamps must be non-decreasing: "
                f"{timestamp} < {self._samples[-1].timestamp}"
            )
        self._samples.append(Sample(timestamp, value))

    @property
    def samples(self) -> Sequence[Sample]:
        """Read-only, oldest-first view of the series."""
        return self._samples

    def __len__(self) -> int:
        return len(self._samples)


BindingValue = int | float | bool | str


@dataclass
class RunState:
    """Shared workflow state: named streams plus scalar bindings (design §6)."""

    streams: dict[str, Stream] = field(default_factory=dict)
    bindings: dict[str, BindingValue] = field(default_factory=dict)

    def record(self, stream: str, timestamp: float, value: float) -> None:
        """Append a measurement, creating the stream on first write."""
        self.streams.setdefault(stream, Stream()).append(timestamp, value)

    def bind(self, name: str, value: BindingValue) -> None:
        """Bind an operator-input scalar for later reference by name."""
        self.bindings[name] = value
