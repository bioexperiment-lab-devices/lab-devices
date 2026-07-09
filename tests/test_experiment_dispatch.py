import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.errors import EvaluationError, InvariantViolationError
from lab_devices.experiment.execute import _run_action
from lab_devices.experiment.state import RunState, Stream
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


def make_ctx(client, workflow=None, *, clock=None, job_timeout=None):
    wf = workflow if workflow is not None else make_workflow([])
    options = RunOptions(clock=clock or FakeClock(), job_timeout=job_timeout)
    state = RunState()
    for name in wf.streams:
        state.streams[name] = Stream()
    return RunContext(client=client, workflow=wf, state=state, options=options)


def cmd(device, verb, params=None, id="blocks[0]"):
    return B.Command(device=device, verb=verb, params=params or {}, id=id)


async def test_immediate_verb_dispatches_and_frees(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    await _run_action(cmd("valve_1", "home", {"position": 1}), ctx)
    assert verbs(fake) == [("valve_1", "home")]
    assert fake.calls[0][2] == {"position": 1}
    ctx.occupancy.acquire("valve_1", frozenset({"motor"}), "blocks[9]")  # slot free again
    assert "valve_1" in ctx.touched


async def test_job_verb_polls_via_clock_and_untracks(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.polls_to_complete_by_cmd["dispense"] = 3  # forces two 0.25s poll sleeps
    clock = FakeClock()
    ctx = make_ctx(client, clock=clock)
    result = await drive(clock, _run_action(cmd("pump_1", "dispense", {"volume_ml": 1.0}), ctx))
    assert result.dispensed_ml == 10.0  # typed DispenseResult from the core
    assert ctx.in_flight == {}
    assert clock.now() > 0  # polling really slept on the fake clock


async def test_expression_params_resolved_at_dispatch(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([], streams={"OD": {}})
    ctx = make_ctx(client, wf)
    ctx.state.record("OD", 0.0, 0.4)
    ctx.state.bind("target", 1.0)
    block = cmd("pump_1", "dispense",
                {"volume_ml": "2.0 * (target - mean(OD, last=100))", "speed_ml_min": 3.0})
    await drive(ctx.clock, _run_action(block, ctx))
    sent = fake.calls[0][2]
    assert sent["volume_ml"] == pytest.approx(1.2)
    assert sent["speed_ml_min"] == 3.0


async def test_string_kind_params_stay_opaque(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    # "forward" would parse as a binding ref and raise if blanket-resolved (carry-forward)
    block = cmd("pump_2", "rotate", {"direction": "forward", "speed_ml_min": 2.0})
    await _run_action(block, ctx)
    assert fake.calls[0][2]["direction"] == "forward"


async def test_int_slot_coerces_integral_float(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    await _run_action(cmd("densitometer_1", "set_led", {"level": "8 / 2"}), ctx)
    sent = fake.calls[0][2]["level"]
    assert sent == 4 and isinstance(sent, int)


async def test_int_slot_rejects_fractional(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    with pytest.raises(EvaluationError, match="requires an integer"):
        await _run_action(cmd("densitometer_1", "set_led", {"level": "7 / 2"}), ctx)
    assert fake.calls == []  # failed before the wire


async def test_unresolvable_param_fails_before_wire(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([], streams={"OD": {}})
    ctx = make_ctx(client, wf)
    with pytest.raises(EvaluationError, match="empty stream window"):
        await _run_action(cmd("pump_1", "dispense", {"volume_ml": "mean(OD)"}), ctx)
    assert fake.calls == []


async def test_mode_open_registers_and_survives_release(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    await _run_action(cmd("pump_2", "rotate", {"direction": "forward", "speed_ml_min": 2.0}), ctx)
    modes = ctx.occupancy.open_modes()
    assert [(m.device, m.mode_verb, m.teardown_verb) for m in modes] == [
        ("pump_2", "rotate", "stop")
    ]
    with pytest.raises(InvariantViolationError):  # motor is mode-held after the block ended
        await _run_action(cmd("pump_2", "dispense", {"volume_ml": 1.0}, id="blocks[1]"), ctx)


async def test_matching_close_closes_and_frees(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    await _run_action(cmd("pump_2", "rotate", {"direction": "forward", "speed_ml_min": 2.0}), ctx)
    await _run_action(cmd("pump_2", "stop", id="blocks[1]"), ctx)
    assert ctx.occupancy.open_modes() == ()
    await drive(ctx.clock, _run_action(cmd("pump_2", "dispense", {"volume_ml": 1.0},
                                           id="blocks[2]"), ctx))  # free again


async def test_runtime_close_on_resolved_params_D7(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client)
    await _run_action(cmd("densitometer_1", "set_led", {"level": 5}), ctx)
    assert len(ctx.occupancy.open_modes()) == 1
    # expression resolving to the teardown literal counts as a close at runtime (D7)
    await _run_action(cmd("densitometer_1", "set_led", {"level": "10 - 10"}, id="blocks[1]"), ctx)
    assert ctx.occupancy.open_modes() == ()


async def test_busy_error_maps_to_invariant_violation_no_retry(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.inject_error("pump_1", "dispense", "busy", "job j-1 in progress")
    ctx = make_ctx(client)
    with pytest.raises(InvariantViolationError, match="busy"):
        await _run_action(cmd("pump_1", "dispense", {"volume_ml": 1.0}), ctx)
    assert verbs(fake) == [("pump_1", "dispense")]  # exactly one attempt, never retried
    events = [e.kind for e in ctx.log_sink.events]
    assert "invariant_violation" in events
    ctx.occupancy.acquire("pump_1", frozenset({"motor"}), "blocks[9]")  # slot rolled back


async def test_failed_call_rolls_back_mode_open(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.inject_error("pump_2", "rotate", "hardware_error", "stall")
    ctx = make_ctx(client)
    from lab_devices import errors as core_errors

    with pytest.raises(core_errors.HardwareError):
        await _run_action(cmd("pump_2", "rotate",
                              {"direction": "forward", "speed_ml_min": 2.0}), ctx)
    assert ctx.occupancy.open_modes() == ()
    ctx.occupancy.acquire("pump_2", frozenset({"motor"}), "blocks[9]")  # rolled back


async def test_job_timeout_keeps_in_flight_entry(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    clock = FakeClock()
    ctx = make_ctx(client, clock=clock, job_timeout=10.0)
    from lab_devices import errors as core_errors

    with pytest.raises(core_errors.JobTimeoutError):
        await drive(clock, _run_action(cmd("pump_1", "dispense", {"volume_ml": 1.0}), ctx))
    assert len(ctx.in_flight) == 1  # still tracked: the finalizer must stop this device
