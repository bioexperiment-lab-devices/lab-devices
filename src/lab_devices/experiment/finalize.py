"""Safe-shutdown finalizer: cancel jobs, tear down modes, sweep. See design 4-exec §11."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from lab_devices.experiment.context import RunContext
from lab_devices.experiment.registry import device_type

_SWEEP: dict[str, tuple[tuple[str, dict[str, Any]], ...]] = {
    "pump": (("stop", {}),),
    "valve": (("stop", {}),),
    "densitometer": (
        ("stop", {}),
        ("stop_monitoring", {}),
        ("set_led", {"level": 0}),
        ("set_thermostat", {"enabled": False}),
    ),
}


def _emit(ctx: RunContext, kind: str, **data: Any) -> None:
    """Best-effort: a raising log sink must never stop the safe-state sweep (§11)."""
    try:
        ctx.emit(kind, **data)
    except BaseException:  # noqa: BLE001 - deliberate, mirrors _issue
        pass


async def run_finalizer(ctx: RunContext) -> list[BaseException]:
    """Best-effort, fixed-order shutdown; a failed step never skips the rest (§11)."""
    errors: list[BaseException] = []
    _emit(ctx, "finalize_started")
    # 1. Cancel in-flight jobs: stop each device that still owns a live job.
    for device_id in dict.fromkeys(entry[0] for entry in ctx.in_flight.values()):
        stopped = await _issue(ctx, device_id, "stop", {}, "job_cancelled", errors)
        if stopped:
            # The stop killed the device's jobs, so the channels an abandoned job was still
            # holding (Occupancy.strand, design 2026-07-14 §3.2) are genuinely free now. Hand
            # them back, exactly as step 2 hands back a mode's channels once its teardown
            # succeeded: `ctx.occupancy` is the live idle oracle behind Console.busy_devices(),
            # and an operator recovering AFTER the run must not find the device busy for ever.
            # `ctx.in_flight` deliberately keeps the record — the run did abandon that job.
            for job_id, (owner, _job) in ctx.in_flight.items():
                if owner == device_id:
                    ctx.occupancy.release_stranded(device_id, job_id)
    # 2. Tear down open modes, most recently opened first.
    for mode in reversed(ctx.occupancy.open_modes()):
        ok = await _issue(
            ctx, mode.device, mode.teardown_verb, dict(mode.teardown_params),
            "teardown_issued", errors,
        )
        if ok:
            ctx.occupancy.register_close(mode.device, mode.mode_verb)
    # 3. Unconditional idempotent safe-state sweep over every touched device.
    for device_id in ctx.touched:
        for verb, params in _SWEEP.get(device_type(device_id), ()):
            await _issue(ctx, device_id, verb, dict(params), "sweep_command", errors)
    _emit(ctx, "finalize_finished", errors=len(errors))
    return errors


async def _issue(
    ctx: RunContext,
    device_id: str,
    verb: str,
    params: dict[str, Any],
    kind: str,
    errors: list[BaseException],
) -> bool:
    """One best-effort call; catches everything (incl. CancelledError) by design —
    an abort arriving mid-finalize must not stop the safe-state sweep."""
    try:
        device = ctx.device(device_id)
        method: Callable[..., Awaitable[Any]] = getattr(device, verb)
        async with ctx.lock(device_id):
            await method(**params)
    except BaseException as exc:
        errors.append(exc)
        _emit(ctx, "finalize_step_failed", device=device_id, verb=verb, error=str(exc))
        return False
    _emit(ctx, kind, device=device_id, verb=verb)
    return True
