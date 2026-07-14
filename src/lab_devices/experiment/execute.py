"""Recursive async executor: trait-driven dispatch over the block tree.
See design 4-exec §7-9."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from lab_devices import errors as core_errors
from lab_devices.experiment import blocks as B
from lab_devices.experiment.context import RunContext
from lab_devices.experiment.durations import parse_duration
from lab_devices.experiment.errors import (
    BlockFailedError,
    EvaluationError,
    InvariantViolationError,
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
    EvaluationError,
    core_errors.InvalidParamsError,
    core_errors.InvalidRequestError,
    core_errors.UnknownCommandError,
    core_errors.UnknownDeviceError,
    core_errors.NotCalibratedError,
    core_errors.NotHomedError,
)


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


async def _await_job(job: Job, device_id: str, ctx: RunContext) -> Any:
    """Clock-driven poll to terminal, then delegate interpretation to job.result()
    (terminal-state result() neither polls nor sleeps). Design 4-exec §6."""
    opts = ctx.options
    deadline = None if opts.job_timeout is None else ctx.clock.now() + opts.job_timeout
    interval = opts.job_poll_interval
    while job.state not in _TERMINAL:
        async with ctx.lock(device_id):
            await job.refresh()
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
    policy = _effective_retry(block, lookup(block.device, block.verb), ctx)
    attempts = 1 if policy is None else policy.attempts
    backoff = 0.0 if policy is None else parse_duration(policy.backoff)
    for attempt in range(1, attempts + 1):
        await ctx.gate.wait()  # a pause during a retry storm quiesces at the next attempt
        try:
            return await _dispatch_action(block, ctx)
        except Exception as exc:
            if attempt == attempts or not _is_retryable(exc):
                raise
            ctx.emit(
                "block_retried", block.id,
                attempt=attempt, of=attempts, error=str(exc),
            )
            await ctx.clock.sleep(backoff)
    raise AssertionError("unreachable: the loop either returns or raises")  # pragma: no cover


async def _dispatch_action(block: B.Command | B.Measure, ctx: RunContext) -> Any:
    """The dispatch pipeline (design 4-exec §7): resolve -> classify -> occupy ->
    invoke -> complete. The occupancy check-and-mark is synchronous (no interleave
    window); the wire lock spans exactly one HTTP call (D2)."""
    trait = lookup(block.device, block.verb)
    params = _resolve_params(block, trait, ctx)
    action = mode_action(block.device, block.verb, params)  # on RESOLVED values (D7)
    closes = action.mode_verb if action is not None and action.kind == "close" else None
    block_id = str(block.id)
    ctx.touched.setdefault(block.device)
    try:
        ctx.occupancy.acquire(block.device, trait.channels, block_id, closes=closes)
    except InvariantViolationError as exc:
        ctx.emit("invariant_violation", block.id, error=str(exc))
        raise
    holding = True
    try:
        device = ctx.device(block.device)
        try:
            async with ctx.lock(block.device):
                result = await _call_verb(device, block.verb, params)
        except core_errors.BusyError as exc:
            ctx.emit("invariant_violation", block.id, error=str(exc))
            raise InvariantViolationError(
                f"hardware reported busy for a statically-proven-free dispatch: {exc}"
            ) from exc
        if trait.completion == "job":
            job: Job = result
            ctx.in_flight[job.job_id] = (block.device, job)
            result = await _await_job(job, block.device, ctx)
        if action is not None and action.kind == "open":
            assert trait.teardown is not None  # every mode entry declares its teardown
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
            ctx.occupancy.release(block.device, trait.channels, block_id)


async def execute_blocks(blocks: list[B.Block], ctx: RunContext) -> None:
    """Serial semantics: children in order; gap_after honored unconditionally (§9)."""
    for block in blocks:
        await execute_block(block, ctx)
        if block.gap_after is not None:
            await ctx.clock.sleep(parse_duration(block.gap_after))


async def execute_block(block: B.Block, ctx: RunContext) -> None:
    """One block: pause gate, per-type execution, exactly-once failure events (§7, §10)."""
    await ctx.gate.wait()
    ctx.emit("block_started", block.id)
    try:
        await _execute_inner(block, ctx)
    except (BlockFailedError, InvariantViolationError):
        raise  # the origin frame already emitted its event
    except BaseExceptionGroup:
        raise  # parallel children emitted their own events (plan 4b)
    except Exception as exc:
        ctx.emit("block_failed", block.id, error=str(exc))
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
    else:
        await execute_blocks(ctx.workflow.groups[block.name].body, ctx)


async def _run_measure(block: B.Measure, ctx: RunContext) -> None:
    """Run the measurement job and stamp (clock.now(), scalar) into the stream (§8)."""
    result = await _run_action(block, ctx)
    field_name = lookup(block.device, block.verb).result_field
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
    TaskGroup's ExceptionGroup propagates unflattened."""
    async with asyncio.TaskGroup() as tg:
        for child in block.children:
            tg.create_task(_parallel_child(child, ctx))


async def _parallel_child(child: B.Block, ctx: RunContext) -> None:
    if child.start_offset is not None:
        await ctx.clock.sleep(parse_duration(child.start_offset))
    await execute_block(child, ctx)
