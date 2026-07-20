"""Recursive async executor: trait-driven dispatch over the block tree.
See design 4-exec §7-9."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from typing import Any

from lab_devices import errors as core_errors
from lab_devices.experiment import blocks as B
from lab_devices.experiment._legacy_ids import legacy_device_type
from lab_devices.experiment.context import RunContext
from lab_devices.experiment.durations import parse_duration
from lab_devices.experiment.errors import (
    AbortSignalError,
    AlarmRecord,
    BlockFailedError,
    EvaluationError,
    InvariantViolationError,
    OrphanedJobError,
    RunAbortedError,
    ToleratedError,
    UnknownVerbError,
)
from lab_devices.experiment.evaluate import Value, evaluate, resolve
from lab_devices.experiment.expr import parse_expression
from lab_devices.experiment.inputs import InputRequest, validate_input_value
from lab_devices.experiment.occupancy import OpenMode
from lab_devices.experiment.registry import ParamSpec, Trait, lookup, mode_action
from lab_devices.experiment.state import Sample
from lab_devices.jobs import Job

_TERMINAL = frozenset({"succeeded", "failed", "cancelled"})

# Errors a retry can never fix: they will fail identically, or they mean the safety
# model itself is broken (design 2026-07-14 §3.1).
_NEVER_RETRY: tuple[type[BaseException], ...] = (
    InvariantViolationError,
    # The channel is held by a job we abandoned and could not stop. Nothing this block does
    # can change that: every attempt is refused identically until the finalizer stops the
    # device. A retry would only spin the block through its whole back-off schedule to reach
    # the same refusal.
    OrphanedJobError,
    EvaluationError,
    core_errors.InvalidParamsError,
    core_errors.InvalidRequestError,
    core_errors.UnknownCommandError,
    core_errors.UnknownDeviceError,
    core_errors.NotCalibratedError,
    core_errors.NotHomedError,
    # A job reports `cancelled` only because someone deliberately stopped the device
    # (Job.cancel() -> device.stop(), the Console/Studio recovery seam). It is the closest
    # sibling of asyncio.CancelledError in the taxonomy: a stop decision, not a transient
    # fault. Re-dispatching would silently undo an operator's stop.
    core_errors.JobCancelledError,
)


def _emit(ctx: RunContext, kind: str, block_id: str | None = None, **data: Any) -> None:
    """Best-effort emit for every site that runs WHILE AN EXCEPTION IS IN FLIGHT — inside an
    `except` arm or a `finally`. Mirrors `finalize._emit` (and `run.py`'s three wrapped emits):
    the sink protocol says `emit()` must never raise (design 5 §8), and here a sink that breaks
    that contract does not merely lose an event, it REPLACES the exception the engine is already
    carrying:

    - Displace an `asyncio.CancelledError` and the operator's abort is gone. `_dispatch_action`'s
      `finally` is on the abort path: the sink's error would surface there instead, `_run_action`'s
      `except Exception` would catch it, `_is_retryable` would say yes, and the retry would
      RE-DISPATCH hardware after `abort()` had already returned. (`_run_action`'s
      `abort_requested` re-check is the second, independent net under that.)
    - Displace an `InvariantViolationError` (the two `invariant_violation` emits) and a broken
      safety invariant becomes an ordinary error — retryable, and tolerable by `on_error`.

    Happy-path emits (`block_started`, `mode_opened`, `measure_recorded`, ...) are deliberately
    NOT wrapped: nothing is in flight there, so a sink that raises is a real fault and should fail
    the run (pinned by test_raising_log_sink_still_finalizes_and_sets_report)."""
    try:
        ctx.emit(kind, block_id, **data)
    except BaseException:  # noqa: BLE001 - deliberate, mirrors finalize._emit
        pass


def _is_retryable(exc: BaseException) -> bool:
    """Allow-by-default over device/transport faults, with a deny-list. CancelledError is
    a BaseException and never reaches here, but the isinstance guard is explicit anyway."""
    if isinstance(exc, asyncio.CancelledError):
        return False
    return not isinstance(exc, _NEVER_RETRY)


def _effective_retry(
    block: B.Command | B.Measure, trait: Trait, ctx: RunContext
) -> B.Retry | None:
    """Block policy wins; otherwise the workflow default — but a blanket default never
    retries a non-idempotent verb (design 2026-07-14 §2.4)."""
    if block.retry is not None:
        return block.retry
    default = ctx.workflow.defaults.retry
    if default is not None and trait.retry_safe:
        return default
    return None


def _condition(text: str, ctx: RunContext) -> bool:
    """Evaluate a boolean condition at this instant (fail-safe, design §6)."""
    value = evaluate(parse_expression(text), ctx.state, ctx.clock.now())
    if not isinstance(value, bool):
        raise EvaluationError(f"condition {text!r} evaluated to non-boolean {value!r}")
    return value


def _resolve_params(
    block: B.Command | B.Measure, trait: Trait, ctx: RunContext
) -> dict[str, Any]:
    """Resolve expression slots at dispatch time; string-kind slots stay opaque
    (Increment-3 carry-forward)."""
    specs = {spec.name: spec for spec in trait.params}
    now = ctx.clock.now()
    resolved: dict[str, Any] = {}
    for name, value in block.params.items():
        spec = specs[name]  # unknown params cannot survive validation (D6)
        if spec.kind == "string":
            resolved[name] = value
        else:
            resolved[name] = _check_kind(resolve(value, ctx.state, now), spec)
    return resolved


def _check_kind(value: Value, spec: ParamSpec) -> Value:
    """Runtime kind check: bool never numeric; int slots coerce integral floats."""
    if spec.kind == "bool":
        if not isinstance(value, bool):
            raise EvaluationError(f"param {spec.name!r} requires a bool, got {value!r}")
        return value
    if isinstance(value, bool):
        raise EvaluationError(f"param {spec.name!r} requires a {spec.kind}, got a boolean")
    if spec.kind == "int":
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise EvaluationError(f"param {spec.name!r} requires an integer, got {value!r}")
    return value  # kind "number": int | float


async def _call_verb(device: Any, verb: str, params: dict[str, Any]) -> Any:
    method: Callable[..., Awaitable[Any]] = getattr(device, verb)
    return await method(**params)


async def _await_job(job: Job, block: B.Command | B.Measure, ctx: RunContext) -> Any:
    """Clock-driven poll to terminal, then delegate interpretation to job.result()
    (terminal-state result() neither polls nor sleeps). Design 4-exec §6.

    A failed poll is NOT a failed job. `job.refresh()` is a `get_job` over the wire, and a
    transient fault on ONE poll (device_unreachable, internal_error, a protocol blip) says
    nothing about the job: it is still running on the hardware. Letting that fault out of here
    would abandon a live job and let `_run_action` re-dispatch ON TOP of it — a second
    concurrent job on the same device, from a single dropped packet, with no author opt-in
    (`densitometer.measure` is retry_safe, so a plain `defaults.retry` reaches this). The right
    answer to a failed poll is to poll again: back off on the clock and ask the job again.

    Bounded by `options.job_poll_max_failures` CONSECUTIVE failures (any successful poll resets
    the count, so a flaky link never accumulates its way to a false failure). Exhausting the
    bound propagates as before, with the job still in `ctx.in_flight` so the finalizer stops the
    device. A deny-listed poll error (e.g. an unknown job_id -> InvalidParamsError) is not
    retried: it will fail identically forever.

    An abort is never swallowed or delayed: `asyncio.CancelledError` is a BaseException, so it
    passes straight through `except Exception` and tears the poll down at once.
    """
    opts = ctx.options
    deadline = None if opts.job_timeout is None else ctx.clock.now() + opts.job_timeout
    interval = opts.job_poll_interval
    failures = 0
    while job.state not in _TERMINAL:
        try:
            async with ctx.lock(block.device):
                await job.refresh()
        except Exception as exc:
            failures += 1
            if failures > opts.job_poll_max_failures or not _is_retryable(exc):
                raise  # NOT untracked: the job may still be running (design §7 step 6)
            _emit(
                ctx, "job_poll_retried", block.id,
                device=block.device, job_id=job.job_id,
                failure=failures, of=opts.job_poll_max_failures, error=str(exc),
            )
        else:
            failures = 0  # the link is alive again; a later blip starts from zero
            if job.state in _TERMINAL:
                break
        if deadline is not None and ctx.clock.now() >= deadline:
            # NOT untracked: the finalizer must stop this device (design §7 step 6).
            raise core_errors.JobTimeoutError(
                f"job {job.job_id} did not finish within {opts.job_timeout}s"
            )
        await ctx.clock.sleep(interval)
        interval = min(interval * 2, opts.job_poll_max)
    ctx.in_flight.pop(job.job_id, None)  # terminal: hardware is done with it
    return await job.result()


async def _run_action(block: B.Command | B.Measure, ctx: RunContext) -> Any:
    """Retry envelope around the dispatch pipeline (design 2026-07-14 §3.2). Each attempt
    re-resolves params against fresh state and re-acquires occupancy — a retry is a fresh
    dispatch, and this is what a fresh dispatch does."""
    policy = _effective_retry(block, lookup(legacy_device_type(block.device), block.verb), ctx)
    attempts = 1 if policy is None else policy.attempts
    backoff = 0.0 if policy is None else parse_duration(policy.backoff)
    for attempt in range(1, attempts + 1):
        await ctx.gate.wait()  # a pause during a retry storm quiesces at the next attempt
        if ctx.abort_requested:
            # Defence in depth: NO attempt is ever dispatched after an abort, however the
            # exception that got us here arrived. A `CancelledError` is a *message* that can be
            # displaced — a log sink that raises inside `_dispatch_action`'s `finally` replaces
            # it outright, and `except Exception` below would then treat the operator's abort as
            # a retryable device fault and re-dispatch on the hardware. `ctx.abort_requested` is
            # a *fact* that cannot be displaced. Same reasoning, and the same wire-level
            # guarantee, as `execute_block`'s guard: after `abort()` returns, nothing more
            # reaches the wire.
            raise asyncio.CancelledError
        started: list[Job] = []  # the job this attempt put on the hardware, if any
        try:
            return await _dispatch_action(block, ctx, started)
        except Exception as exc:
            if attempt == attempts or not _is_retryable(exc):
                raise
            if not await _clear_orphaned_job(exc, started, block, ctx):
                raise  # could not stop the abandoned job; never stack a second one on it
            _emit(
                ctx, "block_retried", block.id,
                attempt=attempt, of=attempts, error=str(exc),
            )
            await ctx.clock.sleep(backoff)
    raise AssertionError("unreachable: the loop either returns or raises")  # pragma: no cover


def _refuse_retry(exc: Exception, reason: str) -> bool:
    """Refuse the retry and let the ORIGINAL error surface, with `reason` folded into its
    message. An `add_note` will not do: `execute_block` emits `block_failed` with
    `error=str(exc)`, which drops `__notes__`, so the reason would never reach the run log,
    the operator, or Studio. Same object, same type, original text preserved as a prefix —
    the error is annotated, never masked (so the deny-list and `on_error` still see a
    JobTimeoutError)."""
    folded = f"{exc}; {reason}"
    exc.args = (folded,)
    if isinstance(exc, core_errors.LabError):
        # LabError.__init__ stores the message a SECOND time. Rewriting only `args` would
        # leave `str(exc)` and `exc.message` disagreeing — the reason visible in the run log
        # and absent from the attribute a reader would reach for first.
        exc.message = folded
    return False


def _modes_a_stop_would_close(device: str, ctx: RunContext) -> tuple[OpenMode, ...]:
    """The open modes a `stop` on this device would silently kill.

    `Job.cancel()` IS `device.stop()` (jobs.py) — device-wide, not job-scoped. The
    densitometer is the one device whose channel groups are disjoint (optics vs thermal), so
    `Occupancy` permits an open mode and a job to be live on it at once; and its `stop`
    declares `optics | thermal`, i.e. it kills the thermostat and the LED as well as the job.
    A device type that declares no `stop` verb has an undeclared blast radius: assume the
    worst rather than the best."""
    try:
        stop_channels: frozenset[str] | None = lookup(legacy_device_type(device), "stop").channels
    except UnknownVerbError:
        stop_channels = None
    modes = ctx.occupancy.open_modes(device)
    if stop_channels is None:
        return modes
    return tuple(mode for mode in modes if mode.channels & stop_channels)


def _doomed_mode_reason(
    job: Job, block: B.Command | B.Measure, doomed: tuple[OpenMode, ...]
) -> str:
    names = ", ".join(sorted(mode.mode_verb for mode in doomed))
    return (
        f"retry refused: clearing the orphaned job {job.job_id} means stopping "
        f"{block.device}, and that stop is device-wide (Job.cancel() is device.stop()) — "
        f"it would have silently closed the open mode(s) {names}, leaving the hardware "
        f"uncontrolled while the run believed the mode was still held"
    )


def _orphan(started: list[Job], ctx: RunContext) -> Job | None:
    """The job THIS attempt put on the hardware and abandoned there, or None.

    "Abandoned" is the general predicate — "is THIS job still tracked?" — and NOT
    `isinstance(exc, JobTimeoutError)`. Tracking is the fact that matters (an untracked job is
    terminal and harmless); the exception type is a proxy for it that a new error class can
    silently invalidate. `_await_job` already has two exits that strand a live job: the timeout,
    and an exhausted poll-failure budget.

    Identity, not just job_id: `ctx.in_flight` is keyed by job_id alone, so two devices
    returning the same id would overwrite each other's entry, and a bare membership test could
    then treat a foreign job as our own orphan — stopping the wrong device's job and untracking
    someone else's entry."""
    if not started:
        return None
    job = started[-1]
    entry = ctx.in_flight.get(job.job_id)
    if entry is None or entry[1] is not job:
        return None  # not tracked (already terminal), or the id belongs to a DIFFERENT job
    return job


async def _clear_orphaned_job(
    exc: Exception, started: list[Job], block: B.Command | B.Measure, ctx: RunContext
) -> bool:
    """May the retry proceed? An attempt that failed with its job still in `ctx.in_flight`
    abandoned a job that is still *physically running* — `_await_job` neither cancels nor
    untracks it (design 4-exec §7 step 6). A retry would then put a SECOND concurrent job on the
    same device: on a real agent the second command draws `busy`, which the executor reports as a
    false `invariant_violation` — the invariant was never violated, the retry raced its own
    orphan. So stop the orphan first. `_orphan` is the trigger, on the general predicate.

    But the stop is device-wide. If it would also close an open mode, we must NOT issue it: the
    mode would die on the hardware while `ctx.occupancy` still held it, and the run would carry
    on — a thermostat believed on and physically off for the rest of a three-week experiment,
    with nothing in the event log to say so. Fail closed instead: refuse the retry.

    Either refusal leaves the original error to surface and the job in `ctx.in_flight`, so the
    finalizer still stops that device (§11) — the abandoned job is never untracked while it may
    still be running on the hardware — AND leaves `_dispatch_action`'s stranded occupancy in
    place, so no later block can dispatch on top of that live job either."""
    job = _orphan(started, ctx)
    if job is None:
        return True
    try:
        async with ctx.lock(block.device):
            # The open-mode check happens HERE, under the lock, and only here: a read taken
            # before queuing for a contended lock can go stale before we actually hold it. The
            # task ahead of us in the queue may be a sibling lane whose own wire call is in
            # flight — `_dispatch_action` awaits it *under this same lock* and calls
            # `register_open` only after releasing it (see the comment there, and
            # test_mode_opening_traits_complete_immediately) — so a `set_thermostat` that has
            # physically switched the heater on can still be absent from `ctx.occupancy` at the
            # moment we'd queue, and present by the moment we're granted the lock. Reading it
            # here, with the wire to this device ours alone, is the only sound moment.
            doomed = _modes_a_stop_would_close(block.device, ctx)
            if doomed:
                return _refuse_retry(exc, _doomed_mode_reason(job, block, doomed))
            await job.cancel()  # Job.cancel() -> device.stop()
    except Exception as cancel_exc:
        return _refuse_retry(
            exc,
            f"retry refused: the orphaned job {job.job_id} could not be cancelled "
            f"({cancel_exc!r}), so a retry would have stacked a second job on {block.device}",
        )
    ctx.in_flight.pop(job.job_id, None)  # the device was stopped; the finalizer need not
    # ...and nothing of ours is running on those channels any more, so give them back: this is
    # the one exit that legitimately clears the occupancy `_dispatch_action` stranded, and the
    # retry about to re-dispatch this very block needs them free.
    ctx.occupancy.release_stranded(block.device, job.job_id)
    _emit(ctx, "job_cancelled", block.id, device=block.device, verb=block.verb)
    return True


async def _dispatch_action(
    block: B.Command | B.Measure, ctx: RunContext, started: list[Job]
) -> Any:
    """The dispatch pipeline (design 4-exec §7): resolve -> classify -> occupy ->
    invoke -> complete. The occupancy check-and-mark is synchronous (no interleave
    window); the wire lock spans exactly one HTTP call (D2)."""
    trait = lookup(legacy_device_type(block.device), block.verb)
    params = _resolve_params(block, trait, ctx)
    action = mode_action(  # on RESOLVED values (D7)
        legacy_device_type(block.device), block.verb, params
    )
    closes = action.mode_verb if action is not None and action.kind == "close" else None
    block_id = str(block.id)
    ctx.touched.setdefault(block.device)
    try:
        ctx.occupancy.acquire(block.device, trait.channels, block_id, closes=closes)
    except InvariantViolationError as exc:
        _emit(ctx, "invariant_violation", block.id, error=str(exc))
        raise
    holding = True
    try:
        device = ctx.device(block.device)
        try:
            async with ctx.lock(block.device):
                result = await _call_verb(device, block.verb, params)
        except core_errors.BusyError as exc:
            _emit(ctx, "invariant_violation", block.id, error=str(exc))
            raise InvariantViolationError(
                f"hardware reported busy for a statically-proven-free dispatch: {exc}"
            ) from exc
        if trait.completion == "job":
            job: Job = result
            ctx.in_flight[job.job_id] = (block.device, job)
            started.append(job)  # so a retry can stop what this attempt abandoned
            result = await _await_job(job, block, ctx)
        if action is not None and action.kind == "open":
            assert trait.teardown is not None  # every mode entry declares its teardown
            # No `await` may land between the wire lock's release (above) and this call.
            # _clear_orphaned_job's open-mode guard reads ctx.occupancy WHILE HOLDING that same
            # lock, and that check is sound only because register_open always runs
            # synchronously right after the lock is released here -- true today only because
            # every mode-opening trait is completion == "immediate" (pinned by
            # test_mode_opening_traits_complete_immediately, tests/test_experiment_registry.py).
            # If a mode-opening verb ever became completion == "job", the `await
            # _await_job(...)` above would land in this exact gap -- and _await_job takes and
            # releases this same wire lock on every poll -- reopening the Critical bug that
            # guard exists to prevent.
            ctx.occupancy.register_open(
                OpenMode(
                    device=block.device,
                    mode_verb=action.mode_verb,
                    teardown_verb=trait.teardown.verb,
                    teardown_params=dict(trait.teardown.params),
                    channels=trait.channels,
                    block_id=block_id,
                )
            )
            holding = False  # slots now belong to the mode, not this block
            ctx.emit("mode_opened", block.id, device=block.device, verb=action.mode_verb)
        elif action is not None and action.kind == "close":
            if ctx.occupancy.register_close(block.device, action.mode_verb) is not None:
                ctx.emit("mode_closed", block.id, device=block.device, verb=action.mode_verb)
        return result
    finally:
        if holding:
            # A job this attempt started and left in `ctx.in_flight` is still PHYSICALLY RUNNING
            # (design 4-exec §7 step 6: `_await_job`'s timeout and poll-budget exits neither
            # cancel nor untrack it). Handing its channels back would tell the rest of the run
            # the device is free, and the next block — or the next loop iteration, or a tolerated
            # block's successor — would dispatch straight on top of it: a second concurrent job
            # on one device, which a real agent answers with `busy`, which `_call_verb` reports
            # as a FALSE invariant violation (never retried, never tolerated: the run dies
            # blaming an invariant that was never violated). `_run_action`'s orphan-clear can
            # stop that job, but it deliberately FAILS CLOSED when the device-wide stop would
            # kill an open mode — the shipped morbidostat's exact shape — and a block carrying
            # `on_error: continue` then absorbs the error and walks on. So the occupancy, not the
            # tolerance, has to be the thing that remembers: keep the slots.
            orphan = _orphan(started, ctx)
            if orphan is None:
                ctx.occupancy.release(block.device, trait.channels, block_id)
            else:
                ctx.occupancy.strand(block.device, trait.channels, block_id, orphan.job_id)
                # `_emit`, not `ctx.emit`: this `finally` runs with the abort's CancelledError in
                # flight, and a raising sink here would REPLACE it — see `_emit`'s docstring.
                _emit(
                    ctx, "job_stranded", block.id,
                    device=block.device, job_id=orphan.job_id,
                    channels=sorted(trait.channels),
                )


async def execute_blocks(blocks: list[B.Block], ctx: RunContext) -> None:
    """Serial semantics: children in order; gap_after honored unconditionally (§9)."""
    for block in blocks:
        await execute_block(block, ctx)
        if block.gap_after is not None:
            await ctx.clock.sleep(parse_duration(block.gap_after))


def _tolerable(exc: BaseException) -> bool:
    """An abort and a broken safety invariant escape every tolerance (design 2026-07-14 §3.3).

    - `asyncio.CancelledError`: an operator abort is not a fault the workflow may absorb. It
      is a BaseException, so `except Exception` never sees it — but `except BaseExceptionGroup`
      would, which is exactly why this predicate recurses into a group.
    - `InvariantViolationError`: a proven-impossible occupancy state. The safety model itself
      is broken; tolerating it would hide that, and the run would carry on dispatching against
      a proof it has just watched fail.
    - `AbortSignalError`: a workflow `abort` block's condition was true — a deliberate,
      workflow-initiated stop (design 2026-07-16 §2.1), not a device fault. An enclosing
      `on_error: continue` absorbing it would silently turn "stop the run" into "carry on",
      which defeats the whole feature.
    - `RunAbortedError`: unreachable inside a block today — its only raise site is `run.py`,
      AFTER the block walk has already returned — but it is the abort error named by design's
      own never-swallow table, and `_tolerate`'s whole reason to exist is defence against a
      one-edit-away mistake. If that raise site ever moved inward, this is where the mistake
      would otherwise become live.
    - `core_errors.BusyError`: today converted to `InvariantViolationError` at its one call
      site (`_dispatch_action`'s `_call_verb`) — a statically-proven-free dispatch drawing
      `busy` IS the invariant violation. A bare `BusyError` surfacing from anywhere else (e.g.
      a future `job.refresh()` / `job.result()` path) must not be laundered into an ordinary,
      tolerable fault just because that one call site forgot to convert it first.
    """
    if isinstance(
        exc,
        (
            asyncio.CancelledError,
            InvariantViolationError,
            AbortSignalError,
            RunAbortedError,
            core_errors.BusyError,
        ),
    ):
        return False
    if isinstance(exc, BaseExceptionGroup):
        # A parallel lane may have been cancelled, or may have violated an invariant. Nesting
        # is possible (a parallel inside a parallel), so recurse rather than scan one level.
        return all(_tolerable(inner) for inner in exc.exceptions)
    return True


def _leaves(exc: BaseException) -> list[BaseException]:
    """Flatten a `BaseExceptionGroup` down to its leaf exceptions, recursing through nested
    groups (a parallel inside a parallel); a bare exception is its own single leaf.

    Exists so a tolerated container never reports the group's own boilerplate `str()`
    ("unhandled errors in a TaskGroup (1 sub-exception)") in place of what actually failed —
    design §3.4's "a run that dropped 40 samples must not look identical to a clean one"
    depends on the message naming the real fault, not the shape that carried it."""
    if isinstance(exc, BaseExceptionGroup):
        result: list[BaseException] = []
        for inner in exc.exceptions:
            result.extend(_leaves(inner))
        return result
    return [exc]


def _tolerate(block: B.Block, exc: BaseException, ctx: RunContext) -> bool:
    """Absorb this block's failure and let the parent proceed (design 2026-07-14 §3.3-3.4).

    True when the failure was absorbed. EVERY tolerance decision in `execute_block` routes
    through this one predicate — including the `except Exception` arm, where `_tolerable` is
    strictly redundant today (a CancelledError is a BaseException and an ExceptionGroup is
    caught above it). That redundancy is the point: the arm order is the only thing standing
    between an operator's abort and a tolerance, and an arm order is one edit away from being
    wrong. This makes the guarantee independent of it.

    The `abort_requested` check is the load-bearing one, and it is NOT redundant with
    `_tolerable`'s CancelledError entry. `asyncio.TaskGroup` DROPS a cancellation that races a
    child error — its docs: it propagates CancelledError "except if there are other errors —
    those have priority". So a `parallel` whose lane fails at the moment the operator aborts
    raises a plain ExceptionGroup with NO CancelledError anywhere inside it (the TaskGroup skips
    cancelled children), and `_tolerable` — which can only inspect what it is handed — sees an
    ordinary tolerable fault and says yes. The abort would be absorbed, the run would carry on
    dispatching hardware, and it would report `completed`. The operator's decision is not a
    fault of the workflow's to absorb: ask the RUN, not the exception."""
    if ctx.abort_requested:
        return False
    if block.on_error != "continue" or not _tolerable(exc):
        return False
    # `str(exc)` is fine for a bare exception, but for a BaseExceptionGroup (a tolerated
    # `parallel` catching its TaskGroup's failure) it is the group's own boilerplate, not the
    # fault that actually happened. _leaves flattens to what really failed, at any nesting
    # depth, so the ONE shape that used to reach report.json and Studio with no indication of
    # the real error no longer does (design 2026-07-14 §3.4).
    message = "; ".join(str(leaf) for leaf in _leaves(exc))
    ctx.tolerated.append(ToleratedError(str(block.id), message))
    _emit(ctx, "block_error_tolerated", block.id, error=message)
    return True


async def execute_block(block: B.Block, ctx: RunContext) -> None:
    """One block: pause gate, per-type execution, exactly-once failure events (§7, §10).

    `on_error: "continue"` absorbs the failure HERE, in this block's own frame, and returns
    normally instead of raising (design 2026-07-14 §3.3). On a parallel CHILD that single fact
    is per-lane fault isolation: `_run_parallel`'s TaskGroup cancels the siblings only when a
    lane *raises*, and a tolerated lane never does — so one bad vial no longer kills the other
    fourteen. On the `parallel` block itself it catches the TaskGroup's ExceptionGroup and
    abandons the whole container, leaving the parent to carry on.

    A tolerated block emits `block_failed` (it did fail) then `block_error_tolerated` — never
    `block_finished`.

    No block STARTS once an abort has been requested. `abort()` cancels the run task, and a
    cancellation normally makes this check unreachable — but a cancellation is a message that
    can be consumed (`asyncio.TaskGroup` drops one that races a child error; see `_tolerate`),
    and `ctx.abort_requested` is a fact that cannot. This is the wire-level backstop for the
    property that actually matters: after `abort()` returns, no further command reaches the
    hardware."""
    await ctx.gate.wait()
    if ctx.abort_requested:
        raise asyncio.CancelledError
    ctx.emit("block_started", block.id)
    try:
        await _execute_inner(block, ctx)
    except (BlockFailedError, InvariantViolationError, AbortSignalError) as exc:
        if _tolerate(block, exc, ctx):  # the origin frame already emitted its event
            return
        raise
    except BaseExceptionGroup as exc:
        if _tolerate(block, exc, ctx):  # parallel children emitted their own events (plan 4b)
            return
        raise
    except asyncio.CancelledError:
        raise  # an abort is never a block failure, and is never tolerated
    except Exception as exc:
        _emit(ctx, "block_failed", block.id, error=str(exc))
        if _tolerate(block, exc, ctx):
            return
        raise BlockFailedError(str(block.id), str(exc)) from exc
    ctx.emit("block_finished", block.id)


async def _execute_inner(block: B.Block, ctx: RunContext) -> None:
    if isinstance(block, B.Command):
        await _run_action(block, ctx)
    elif isinstance(block, B.Measure):
        await _run_measure(block, ctx)
    elif isinstance(block, B.OperatorInput):
        await _run_operator_input(block, ctx)
    elif isinstance(block, B.Wait):
        await ctx.clock.sleep(parse_duration(block.duration))
    elif isinstance(block, B.Serial):
        await execute_blocks(block.children, ctx)
    elif isinstance(block, B.Parallel):
        await _run_parallel(block, ctx)
    elif isinstance(block, B.Loop):
        await _run_loop(block, ctx)
    elif isinstance(block, B.Branch):
        await _run_branch(block, ctx)
    elif isinstance(block, B.Compute):
        await _run_compute(block, ctx)
    elif isinstance(block, B.Record):
        await _run_record(block, ctx)
    elif isinstance(block, B.Abort):
        await _run_abort(block, ctx)
    elif isinstance(block, B.Alarm):
        await _run_alarm(block, ctx)
    elif isinstance(block, B.GroupRef):
        await execute_blocks(ctx.workflow.groups[block.name].body, ctx)
    else:
        # ForEach is spliced away before a workflow reaches the executor (Increment 7);
        # reaching here means expansion was skipped.
        raise AssertionError(f"unreachable: unexpanded {type(block).__name__}")  # pragma: no cover


async def _run_measure(block: B.Measure, ctx: RunContext) -> None:
    """Run the measurement job and stamp (clock.now(), scalar) into the stream (§8)."""
    result = await _run_action(block, ctx)
    field_name = lookup(legacy_device_type(block.device), block.verb).result_field
    if field_name is None:  # unreachable for validated workflows
        raise EvaluationError(f"verb {block.verb!r} yields no measurement scalar")
    if isinstance(result, dict):
        value = result.get(field_name)
    else:
        value = getattr(result, field_name, None)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(
            f"measure result field {field_name!r} is missing or non-numeric: {value!r}"
        )
    ts = ctx.clock.now()
    fvalue = float(value)
    ctx.state.record(block.into, ts, fvalue)
    sink = ctx.stream_sinks.get(block.into)
    if sink is not None:
        sink.write(Sample(ts, fvalue))
    ctx.emit("measure_recorded", block.id, stream=block.into, value=fvalue)


def _eval_value(value: B.ValueExpr, ctx: RunContext, now: float) -> Value:
    """Shared value-slot evaluation for compute/record (design §3)."""
    return resolve(value, ctx.state, now)


async def _run_compute(block: B.Compute, ctx: RunContext) -> None:
    """Evaluate and bind a derived scalar; number or boolean (design §3.1)."""
    result = _eval_value(block.value, ctx, ctx.clock.now())
    if isinstance(result, float) and not math.isfinite(result):
        raise EvaluationError(
            f"compute into {block.into!r} got a non-finite value {result!r}"
        )
    ctx.state.bind(block.into, result)
    ctx.emit("binding_computed", block.id, name=block.into, value=result)


async def _run_record(block: B.Record, ctx: RunContext) -> None:
    """Evaluate and append a derived number to a declared stream (design §3.2)."""
    now = ctx.clock.now()  # single evaluation instant: value expr and sample share it
    result = _eval_value(block.value, ctx, now)
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise EvaluationError(
            f"record into {block.into!r} requires a number, got {result!r}"
        )
    # A direct int/float literal (ValueExpr) reaches here unchecked by resolve(); an oversized
    # int (e.g. 10**400) overflows both math.isfinite and float(), so guard the conversion and
    # normalize BOTH failures to EvaluationError rather than leaking a raw OverflowError.
    try:
        value = float(result)
    except OverflowError as exc:
        raise EvaluationError(
            f"record into {block.into!r} got a non-finite value {result!r}"
        ) from exc
    if not math.isfinite(value):
        raise EvaluationError(
            f"record into {block.into!r} got a non-finite value {result!r}"
        )
    ctx.state.record(block.into, now, value)
    sink = ctx.stream_sinks.get(block.into)
    if sink is not None:
        sink.write(Sample(now, value))
    ctx.emit("sample_recorded", block.id, stream=block.into, value=value)


async def _run_abort(block: B.Abort, ctx: RunContext) -> None:
    """A true condition is a deliberate, non-tolerable stop (design 2026-07-16 §2.1). Emit the
    event best-effort (a raising sink must not displace the abort), then raise."""
    if _condition(block.if_, ctx):
        _emit(ctx, "abort_raised", block.id, message=block.message)
        raise AbortSignalError(str(block.id), block.message)


async def _run_alarm(block: B.Alarm, ctx: RunContext) -> None:
    """A true condition flags and continues (design 2026-07-16 §2.2)."""
    if _condition(block.if_, ctx):
        ctx.alarms.append(AlarmRecord(str(block.id), block.message))
        ctx.emit("alarm_raised", block.id, message=block.message)


async def _run_operator_input(block: B.OperatorInput, ctx: RunContext) -> None:
    """Request, validate fail-safe, bind (§8). Only this lane blocks."""
    request = InputRequest(
        name=block.name, type=block.type, prompt=block.prompt,
        min=block.min, max=block.max, choices=block.choices, block_id=str(block.id),
    )
    ctx.emit("input_requested", block.id, name=block.name)
    value = validate_input_value(request, await ctx.inputs.request(request))
    ctx.state.bind(block.name, value)
    ctx.emit("input_bound", block.id, name=block.name, value=value)


async def _run_loop(block: B.Loop, ctx: RunContext) -> None:
    """Loop semantics per design §8/§9: post-test default, pace is a floor from
    iteration start (both modes), no trailing pace, gate re-checked per iteration."""
    pace = parse_duration(block.pace) if block.pace is not None else None
    iterations = 0
    while True:
        await ctx.gate.wait()  # quiesce point at each iteration top (design §10)
        if block.until is not None and block.check == "before" and _condition(block.until, ctx):
            break
        started = ctx.clock.now()
        await execute_blocks(block.body, ctx)
        iterations += 1
        if block.until is not None and block.check == "after" and _condition(block.until, ctx):
            break
        if block.count is not None and iterations >= block.count:
            break
        if pace is not None:
            remaining = pace - (ctx.clock.now() - started)
            if remaining > 0:
                await ctx.clock.sleep(remaining)  # floor, not deadline (design §8)


async def _run_branch(block: B.Branch, ctx: RunContext) -> None:
    if _condition(block.if_, ctx):
        await execute_blocks(block.then, ctx)
    elif block.else_ is not None:
        await execute_blocks(block.else_, ctx)


async def _run_parallel(block: B.Parallel, ctx: RunContext) -> None:
    """One task per child (design §9). Device-distinctness is statically proven; the
    occupancy model is the runtime net. A failing child cancels its siblings; the
    TaskGroup's ExceptionGroup propagates unflattened.

    Except when an abort raced a lane failure. `asyncio.TaskGroup` gives errors priority over a
    cancellation and DROPS the CancelledError: the group it raises then carries only the lane's
    fault, and nothing downstream — not `_tolerable`, not `run.py`'s `isinstance(error,
    CancelledError)` status test — can tell an abort happened. The run would report `failed` at
    best and, with `on_error: continue` on this block, `completed` at worst. `ctx.abort_requested`
    is the fact the TaskGroup cannot consume: restore the cancellation the abort was owed, here,
    at the one frame that swallowed it. The lanes' own failures are already in the run log
    (each emitted `block_failed` in its own frame), so `from None` loses nothing: what the
    operator asked for, and what the report must say, is `aborted`."""
    try:
        async with asyncio.TaskGroup() as tg:
            for child in block.children:
                tg.create_task(_parallel_child(child, ctx))
    except BaseExceptionGroup:
        if ctx.abort_requested:
            raise asyncio.CancelledError from None
        raise


async def _parallel_child(child: B.Block, ctx: RunContext) -> None:
    if child.start_offset is not None:
        await ctx.clock.sleep(parse_duration(child.start_offset))
    await execute_block(child, ctx)
