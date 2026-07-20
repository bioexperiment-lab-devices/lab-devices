import asyncio

import pytest

from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.execute import _run_action, execute_blocks
from lab_devices.experiment.finalize import run_finalizer
from lab_devices.experiment.state import RunState
from tests.experiment_run_helpers import (
    STANDARD_ROLES,
    add_standard_devices,
    make_workflow,
    role_devices,
    verbs,
)
from tests.fakeclock import FakeClock, drive


def make_ctx(client, workflow=None, *, clock=None):
    wf = workflow if workflow is not None else make_workflow([], roles=STANDARD_ROLES)
    return RunContext(client=client, workflow=wf, state=RunState(),
                      options=RunOptions(clock=clock or FakeClock()),
                      role_devices=role_devices(wf))


async def test_untouched_run_sweeps_nothing(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    errors = await run_finalizer(ctx)
    assert errors == [] and fake.calls == []
    assert [e.kind for e in ctx.log_sink.events] == [
        "finalize_started", "finalize_finished",
    ]


async def test_fixed_order_jobs_modes_sweep(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    from lab_devices.experiment import blocks as B

    # open a rotate mode on pump_2, thermostat on densitometer_1, then hold a job on pump_1
    await _run_action(B.Command(device="pump_2", verb="rotate",
                                params={"direction": "forward", "speed_ml_min": 2.0},
                                id="b0"), ctx)
    await _run_action(B.Command(device="densitometer_1", verb="set_thermostat",
                                params={"enabled": True, "target_c": 37.0}, id="b1"), ctx)
    fake.hold_job("dispense")
    device = ctx.device("pump_1")
    job = await device.dispense(volume_ml=1.0)  # started outside _run_action on purpose
    ctx.in_flight[job.job_id] = ("pump_1", job)
    ctx.touched.setdefault("pump_1")
    fake.calls.clear()

    errors = await run_finalizer(ctx)
    assert errors == []
    assert verbs(fake) == [
        ("pump_1", "stop"),                     # 1: cancel in-flight job
        ("densitometer_1", "set_thermostat"),   # 2: teardowns LIFO (thermostat opened last)
        ("pump_2", "stop"),
        ("pump_2", "stop"),                     # 3: sweep in touched order (pump_2 first)
        ("densitometer_1", "stop"),
        ("densitometer_1", "stop_monitoring"),
        ("densitometer_1", "set_led"),
        ("densitometer_1", "set_thermostat"),
        ("pump_1", "stop"),
    ]
    # teardown params are the registry literals
    teardown_call = fake.calls[1]
    assert teardown_call[2] == {"enabled": False}
    sweep_led = [c for c in fake.calls if c[1] == "set_led"]
    assert sweep_led[0][2] == {"level": 0}
    assert ctx.occupancy.open_modes() == ()  # deregistered on successful teardown


async def test_best_effort_never_skips_sweep(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    from lab_devices.experiment import blocks as B

    await _run_action(B.Command(device="pump_2", verb="rotate",
                                params={"direction": "forward", "speed_ml_min": 2.0},
                                id="b0"), ctx)
    ctx.touched.setdefault("densitometer_1")
    fake.calls.clear()
    fake.inject_error("pump_2", "stop", "hardware_error", "stall")   # teardown fails
    fake.inject_error("densitometer_1", "stop", "hardware_error", "x")  # 1st sweep verb fails

    errors = await run_finalizer(ctx)
    # teardown pump_2 stop fails (1); sweep pump_2 stop succeeds (queue drained);
    # sweep densitometer stop fails (2); remaining densitometer verbs still issued
    assert len(errors) == 2
    assert verbs(fake) == [
        ("pump_2", "stop"),                    # teardown attempt (fails)
        ("pump_2", "stop"),                    # sweep (succeeds)
        ("densitometer_1", "stop"),            # sweep (fails)
        ("densitometer_1", "stop_monitoring"),  # sweep continues past the failure
        ("densitometer_1", "set_led"),
        ("densitometer_1", "set_thermostat"),
    ]
    failed = [e.kind for e in ctx.log_sink.events if e.kind == "finalize_step_failed"]
    assert len(failed) == 2
    assert len(ctx.occupancy.open_modes()) == 1  # failed teardown stays registered


async def test_finalizer_after_real_failed_run(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    ctx = make_ctx(client, wf)
    from lab_devices.experiment.errors import BlockFailedError

    with pytest.raises(BlockFailedError):
        await drive(ctx.clock, execute_blocks(wf.blocks, ctx))
    errors = await run_finalizer(ctx)
    assert errors == []
    assert ctx.in_flight == {}  # failed job reached terminal state -> untracked
    # calls 0-1 are the run itself (rotate, dispense); then the finalizer:
    assert verbs(fake)[2:] == [
        ("pump_2", "stop"),  # teardown of the still-open rotate
        ("pump_2", "stop"),  # sweep pump_2 (touched first)
        ("pump_1", "stop"),  # sweep pump_1; densitometer never touched -> not swept
    ]


async def test_cancelled_error_mid_sweep_never_skips(fake_client):
    """Abort arriving mid-finalize must not stop the sweep (design 4-exec §11)."""
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    ctx.touched.setdefault("densitometer_1")
    device = ctx.device("densitometer_1")

    async def cancelled_stop() -> None:
        raise asyncio.CancelledError

    device.stop = cancelled_stop  # type: ignore[method-assign]  # first sweep verb cancelled
    errors = await run_finalizer(ctx)
    assert len(errors) == 1 and isinstance(errors[0], asyncio.CancelledError)
    assert verbs(fake) == [  # remaining sweep verbs still issued after the cancellation
        ("densitometer_1", "stop_monitoring"),
        ("densitometer_1", "set_led"),
        ("densitometer_1", "set_thermostat"),
    ]
    failed = [e for e in ctx.log_sink.events if e.kind == "finalize_step_failed"]
    assert len(failed) == 1 and failed[0].data["verb"] == "stop"
