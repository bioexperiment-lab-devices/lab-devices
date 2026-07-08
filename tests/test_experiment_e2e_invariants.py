# tests/test_experiment_e2e_invariants.py
"""Flagships: BusyError invariant path (spec §16 #8) and D7 runtime classification."""
import pytest

from lab_devices.experiment import ExperimentRun, InvariantViolationError, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


def make_run(client, wf):
    return ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))


async def test_flagship_busy_error_is_invariant_violation_never_retried(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.inject_error("pump_1", "dispense", "busy", "job j-0 in progress")
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = make_run(client, wf)
    with pytest.raises(InvariantViolationError):
        await drive(run._options.clock, run.execute())
    assert run.report.status == "failed"
    dispenses = [v for v in verbs(fake) if v[1] == "dispense"]
    assert len(dispenses) == 1  # the call log proves a single attempt: never retried
    assert verbs(fake)[-1] == ("pump_1", "stop")  # finalizer swept the touched device
    kinds = [e.kind for e in run.report.log.events]
    assert "invariant_violation" in kinds


async def test_d7_expression_close_registers_no_mode(fake_client):
    """A mode verb whose expression params resolve to the teardown literal is a CLOSE at
    runtime (D7): no mode registered, no teardown issued — only the sweep touches it.
    (The validator conservatively calls it an open, which is why nothing may follow it
    on the channel — but it validates standalone.)"""
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "densitometer_1", "verb": "set_led",
                     "params": {"level": "10 - 10"}}},
    ])
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    kinds = [e.kind for e in report.log.events]
    assert "mode_opened" not in kinds
    assert "teardown_issued" not in kinds  # nothing was open at run end
    led_levels = [c[2]["level"] for c in fake.calls if c[1] == "set_led"]
    assert led_levels == [0, 0]  # the block's own call, then the sweep's — both closes
