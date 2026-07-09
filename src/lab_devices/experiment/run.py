"""Public run facade: validation gate, lifecycle, outcome reporting.
See design 4-exec §3, §10-12."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from lab_devices.client import LabClient
from lab_devices.experiment import blocks as B
from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.errors import (
    ExperimentRunError,
    FinalizeError,
    PersistenceError,
    RunAbortedError,
)
from lab_devices.experiment.execute import execute_blocks
from lab_devices.experiment.finalize import run_finalizer
from lab_devices.experiment.persist import SinkSet
from lab_devices.experiment.runlog import RunLogSink
from lab_devices.experiment.state import RunState, Stream
from lab_devices.experiment.validate import validate
from lab_devices.experiment.workflow import Workflow


def assign_block_ids(workflow: Workflow) -> None:
    """Engine-assigned structural ids matching validator diagnostic paths (4-exec §13)."""

    def walk(blocks: list[B.Block], prefix: str) -> None:
        for i, block in enumerate(blocks):
            path = f"{prefix}[{i}]"
            block.id = path
            if isinstance(block, (B.Serial, B.Parallel)):
                walk(block.children, f"{path}.children")
            elif isinstance(block, B.Loop):
                walk(block.body, f"{path}.body")
            elif isinstance(block, B.Branch):
                walk(block.then, f"{path}.then")
                if block.else_ is not None:
                    walk(block.else_, f"{path}.else")

    walk(workflow.blocks, "blocks")
    for name, group in workflow.groups.items():
        walk(group.body, f"groups[{name!r}].body")


@dataclass
class RunReport:
    """Outcome of one execution (design 4-exec §12); set before execute() raises."""

    status: str  # "completed" | "failed" | "aborted" | "cancelled"
    error: BaseException | None
    finalize_errors: tuple[BaseException, ...]
    state: RunState
    log: RunLogSink
    persistence_errors: tuple[BaseException, ...] = ()


class ExperimentRun:
    """One workflow execution: validates at construction (D6), single-shot execute()."""

    def __init__(
        self, client: LabClient, workflow: Workflow, options: RunOptions | None = None
    ) -> None:
        validate(workflow)  # the runtime's safety model IS the static proof (D6)
        assign_block_ids(workflow)
        self._workflow = workflow
        self._options = options or RunOptions()
        state = RunState()
        for stream_name in workflow.streams:
            state.streams[stream_name] = Stream()  # pre-created: count()==0 (§3)
        self._ctx = RunContext(
            client=client, workflow=workflow, state=state, options=self._options
        )
        self._task: asyncio.Task[object] | None = None
        self._started = False
        self._finalizing = False
        self.report: RunReport | None = None
        self._sinks: SinkSet | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._sinks_closed = False

    # ---- control plane (design §10; behavioral tests in plan 4b) ----
    def pause(self) -> None:
        """Quiesce dispatch: in-flight jobs finish, open modes keep running."""
        if not self._ctx.gate.is_set():
            return
        self._ctx.gate.clear()
        if self._started:
            self._ctx.emit("paused")

    def resume(self) -> None:
        if self._ctx.gate.is_set():
            return
        self._ctx.gate.set()
        if self._started:
            self._ctx.emit("resumed")

    def abort(self) -> None:
        """Operator abort: cancel dispatch; the finalizer still reaches safe state (§10)."""
        ctx = self._ctx
        first = not ctx.abort_requested
        ctx.abort_requested = True
        if first and self._task is not None and not self._finalizing:
            self._task.cancel()
        if self._started and first and self.report is None:
            try:
                ctx.emit("abort_requested")
            except BaseException:  # a raising sink must never block the abort path (§8)
                pass

    # ---- control-plane seams for Console (design 5 §9) ----
    def is_device_busy(self, device_id: str) -> bool:
        return self._ctx.occupancy.is_busy(device_id)

    def busy_devices(self) -> set[str]:
        return self._ctx.occupancy.busy_devices()

    def wire_lock(self, device_id: str) -> asyncio.Lock:
        """The per-device wire lock (D2); introspection serializes on it during a live run."""
        return self._ctx.lock(device_id)

    # ---- lifecycle (design §3, §11-12) ----
    async def execute(self) -> RunReport:
        if self._started:
            raise ExperimentRunError("execute() may only be called once per ExperimentRun")
        self._started = True
        ctx = self._ctx
        try:
            sinks = SinkSet.build(
                self._workflow, self._options.output_dir, self._options.log_sink
            )
        except PersistenceError as exc:
            # RunReport.log is the resolved sink (§5): ctx.log_sink already holds the
            # injected/default sink from RunContext.__post_init__ (NEW-3).
            self.report = RunReport("failed", exc, (), ctx.state, ctx.log_sink)
            raise
        self._sinks = sinks
        ctx.log_sink = sinks.log_sink
        ctx.stream_sinks = sinks.stream_sinks
        self._task = asyncio.current_task()
        try:
            ctx.emit("run_started")
        except BaseException:  # a raising custom sink must not skip finalize (design 5 §8)
            pass
        if sinks.has_disk:
            self._flush_task = asyncio.ensure_future(self._flush_loop())
        error: BaseException | None = None
        try:
            if ctx.abort_requested:
                raise asyncio.CancelledError
            await execute_blocks(self._workflow.blocks, ctx)
        except BaseException as exc:
            error = exc
        try:
            await self._stop_flush_task()
        except asyncio.CancelledError as exc:
            if error is None:
                error = exc
        self._finalizing = True
        try:
            finalize_errors = tuple(await run_finalizer(ctx))
        except BaseException as fin_exc:  # finalizer failed catastrophically: still report
            finalize_errors = (fin_exc,)
        if error is not None:
            for fin_err in finalize_errors:
                error.add_note(f"finalizer: {fin_err!r}")
        cancelled = isinstance(error, asyncio.CancelledError)
        aborted = cancelled and ctx.abort_requested
        status = (
            "aborted" if aborted
            else "cancelled" if cancelled
            else "failed" if error is not None
            else "completed"
        )
        try:
            ctx.emit("run_finished", status=status)
        except BaseException:  # a raising log sink must not abort reporting (§11)
            pass
        self._flush_and_close_sinks()  # capture run_finished + any post-finalize event
        # Built AFTER close so persistence_errors() captures any flush/close failure (F2).
        self.report = RunReport(
            status=status, error=error, finalize_errors=finalize_errors,
            state=ctx.state, log=sinks.log_sink,
            persistence_errors=sinks.persistence_errors(),
        )
        if cancelled:
            assert error is not None  # isinstance check above guarantees this (mypy narrowing)
            if aborted:  # operator abort (wired in plan 4b Task 3)
                if self._task is not None:
                    self._task.uncancel()
                raise RunAbortedError("run aborted by operator") from error
            raise error  # external cancellation must propagate (asyncio correctness)
        if error is not None:
            raise error
        if finalize_errors:
            raise FinalizeError(finalize_errors)  # D8
        return self.report

    async def _flush_loop(self) -> None:
        """Periodic durability flush; bounds on-disk staleness (design 5 §4, I2)."""
        interval = self._options.flush_interval
        while True:
            await self._ctx.clock.sleep(interval)
            if self._sinks is not None:
                self._sinks.flush_all()

    async def _stop_flush_task(self) -> None:
        task = self._flush_task
        if task is None:
            return
        self._flush_task = None
        task.cancel()
        current = asyncio.current_task()
        before = current.cancelling() if current is not None else 0
        try:
            await task
        except asyncio.CancelledError:
            if current is not None and current.cancelling() > before:
                raise  # the RUN task itself was cancelled during the await, not the flush task

    def _flush_and_close_sinks(self) -> None:
        if self._sinks is not None and not self._sinks_closed:
            try:
                self._sinks.flush_all()
                self._sinks.close_all()
            except BaseException:  # a foreign sink's flush/close must not unset the report
                pass
            self._sinks_closed = True
