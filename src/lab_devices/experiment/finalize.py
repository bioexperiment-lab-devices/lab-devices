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


async def run_finalizer(ctx: RunContext) -> list[BaseException]:
    """Best-effort, fixed-order shutdown; a failed step never skips the rest (§11)."""
    errors: list[BaseException] = []
    ctx.emit("finalize_started")
    # 1. Cancel in-flight jobs: stop each device that still owns a live job.
    for device_id in dict.fromkeys(entry[0] for entry in ctx.in_flight.values()):
        await _issue(ctx, device_id, "stop", {}, "job_cancelled", errors)
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
    ctx.emit("finalize_finished", errors=len(errors))
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
        ctx.emit("finalize_step_failed", device=device_id, verb=verb, error=str(exc))
        return False
    ctx.emit(kind, device=device_id, verb=verb)
    return True
