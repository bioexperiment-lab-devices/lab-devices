"""Run-scoped context threaded through the executor. See design 4-exec §5."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lab_devices.client import LabClient
from lab_devices.devices.base import Device
from lab_devices.experiment.clock import Clock, MonotonicClock
from lab_devices.experiment.errors import AlarmRecord, ToleratedError
from lab_devices.experiment.inputs import OperatorInputProvider, UnattendedInputProvider
from lab_devices.experiment.occupancy import Occupancy
from lab_devices.experiment.persist import StreamSink
from lab_devices.experiment.runlog import InMemoryRunLog, RunEvent, RunLogSink
from lab_devices.experiment.state import RunState
from lab_devices.experiment.workflow import Workflow
from lab_devices.jobs import Job


@dataclass
class RunOptions:
    """User-tunable executor knobs (design 4-exec §3; disk persistence design 5 §5)."""

    clock: Clock = field(default_factory=MonotonicClock)
    input_provider: OperatorInputProvider = field(default_factory=UnattendedInputProvider)
    log_sink: RunLogSink | None = None  # None -> resolved from persistence config at run start
    output_dir: Path | str | None = None  # spec §5: coerced to Path in SinkSet.build
    flush_interval: float = 30.0
    job_poll_interval: float = 0.25
    job_poll_max: float = 2.0
    job_timeout: float | None = None
    job_poll_max_failures: int = 5
    # Consecutive `get_job` failures tolerated before the fault propagates. A failed poll is
    # NOT a failed job: the job is still running on the hardware, so the answer to a transient
    # blip is to poll again, never to re-dispatch (design 2026-07-14 §3.2). This lives here and
    # not on the block's `Retry` because polling is a pure read of job state — always safe to
    # repeat, even for a non-idempotent verb with no retry policy at all, so it must not be
    # gated by one. It tunes the same loop as job_poll_interval / job_poll_max / job_timeout.
    role_mapping: dict[str, str] = field(default_factory=dict)
    # Role -> physical device id for THIS run (design 2026-07-20 §5.2). Overrides a role's
    # own `device:`. Resolved and checked for injectivity once, in run._resolve_roles.


def _running_gate() -> asyncio.Event:
    gate = asyncio.Event()
    gate.set()
    return gate


@dataclass
class RunContext:
    """Everything one run threads through the recursive walk (design 4-exec §5)."""

    client: LabClient
    workflow: Workflow
    state: RunState
    options: RunOptions
    occupancy: Occupancy = field(default_factory=Occupancy)
    devices: dict[str, Device] = field(default_factory=dict)
    role_devices: dict[str, str] = field(default_factory=dict)
    locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    touched: dict[str, None] = field(default_factory=dict)
    in_flight: dict[str, tuple[str, Job]] = field(default_factory=dict)
    tolerated: list[ToleratedError] = field(default_factory=list)  # on_error (§3.4)
    alarms: list[AlarmRecord] = field(default_factory=list)  # alarm blocks that fired (§4.4)
    gate: asyncio.Event = field(default_factory=_running_gate)
    abort_requested: bool = False
    log_sink: RunLogSink = field(default_factory=InMemoryRunLog)
    stream_sinks: dict[str, StreamSink | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.options.log_sink is not None:
            self.log_sink = self.options.log_sink

    @property
    def clock(self) -> Clock:
        return self.options.clock

    @property
    def inputs(self) -> OperatorInputProvider:
        return self.options.input_provider

    def device(self, role: str) -> Device:
        """Resolve a ROLE to its LabClient handle. The one place in the engine where a
        physical device id is used — the wire boundary (design 2026-07-20 §5.2). Every
        other structure (locks, occupancy, touched, in_flight, events) keys on the role
        name, which injectivity (§5.4) makes equivalent and which is what the author
        wrote."""
        if role not in self.devices:
            self.devices[role] = self.client.device(self.role_devices[role])
        return self.devices[role]

    def lock(self, role: str) -> asyncio.Lock:
        """Wire-serialization lock (D2): held only across one HTTP call, never across
        a job wait or a mode scope. Keyed by ROLE, like every other engine structure."""
        if role not in self.locks:
            self.locks[role] = asyncio.Lock()
        return self.locks[role]

    def emit(self, kind: str, block_id: str | None = None, **data: Any) -> None:
        self.log_sink.emit(RunEvent(self.clock.now(), kind, block_id, dict(data)))
