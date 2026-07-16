import pytest

from lab_devices.experiment import ExperimentRun, RunOptions
from lab_devices.experiment.errors import AbortSignalError
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock


def _run(client, wf):
    return ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))


async def test_abort_false_is_noop(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"abort": {"if": "false", "message": "never"}},
        {"command": {"device": "pump_1", "verb": "stop"}},
    ])
    report = await _run(client, wf).execute()
    assert report.status == "completed"
    assert ("pump_1", "stop") in verbs(fake)


async def test_abort_true_stops_run_and_skips_successor(fake_client):
    # WIRE assertion: the post-abort dispense must never reach the hardware.
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"abort": {"if": "true", "message": "stop now"}},
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = _run(client, wf)
    with pytest.raises(AbortSignalError):
        await run.execute()
    assert run.report.status == "aborted"                      # MUTATION: except-arm entry
    assert ("pump_1", "dispense") not in verbs(fake)
    kinds = [e.kind for e in run.report.log.events]
    assert "abort_raised" in kinds
    assert "finalize_finished" in kinds


async def test_abort_runs_finalizer_over_touched_device(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"abort": {"if": "true", "message": "stop"}},
    ])
    run = _run(client, wf)
    with pytest.raises(AbortSignalError):
        await run.execute()
    assert run.report.status == "aborted"
    assert ("pump_1", "stop") in verbs(fake)  # rotate teardown + sweep swept the device safe
    assert run._ctx.occupancy.open_modes() == ()


async def test_abort_not_tolerated_by_enclosing_on_error(fake_client):
    # MUTATION: remove AbortSignalError from _tolerable -> this run would "complete".
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"serial": {"children": [
            {"abort": {"if": "true", "message": "stop"}},
        ]}, "on_error": "continue"},
        {"command": {"device": "pump_2", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = _run(client, wf)
    with pytest.raises(AbortSignalError):
        await run.execute()
    assert run.report.status == "aborted"
    assert ("pump_2", "dispense") not in verbs(fake)


async def test_abort_in_parallel_lane_reports_aborted(fake_client):
    # MUTATION: remove _contains_abort's group recursion -> status becomes "failed".
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"parallel": {"children": [
            {"abort": {"if": "true", "message": "lane stop"}},
            {"command": {"device": "pump_1", "verb": "rotate",
                         "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        ]}, "on_error": "continue"},
    ])
    run = _run(client, wf)
    with pytest.raises(BaseException):  # AbortSignalError or the ExceptionGroup carrying it
        await run.execute()
    assert run.report.status == "aborted"
