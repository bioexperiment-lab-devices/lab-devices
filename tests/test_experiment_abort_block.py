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
    #
    # The validator now forbids AUTHORING a tolerant ancestor over an abort (fix for finding
    # I1: a tolerant ancestor can absorb the abort condition's own eval failure and silently
    # disable the stop) -- so this exact document no longer loads. The property under test
    # here is a *different*, still-real one: the executor's independent defense-in-depth,
    # that on_error: "continue" never swallows an AbortSignalError even if one somehow
    # reaches a tolerant frame. Build a validator-clean document, then flip the flag
    # post-construction to exercise that executor guarantee directly.
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"serial": {"children": [
            {"abort": {"if": "true", "message": "stop"}},
        ]}},
        {"command": {"device": "pump_2", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run = _run(client, wf)
    run._workflow.blocks[0].on_error = "continue"
    with pytest.raises(AbortSignalError):
        await run.execute()
    assert run.report.status == "aborted"
    assert ("pump_2", "dispense") not in verbs(fake)


async def test_abort_in_parallel_lane_reports_aborted(fake_client):
    # MUTATION: remove _contains_abort's group recursion -> status becomes "failed".
    #
    # Same rationale as test_abort_not_tolerated_by_enclosing_on_error above: the validator
    # now forbids authoring on_error: "continue" over an abort (finding I1), so the tolerant
    # flag is applied post-construction to exercise the executor's group-recursion guarantee
    # directly, independent of the validator.
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"parallel": {"children": [
            {"abort": {"if": "true", "message": "lane stop"}},
            {"command": {"device": "pump_1", "verb": "rotate",
                         "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        ]}},
    ])
    run = _run(client, wf)
    run._workflow.blocks[0].on_error = "continue"
    # AbortSignalError, or the ExceptionGroup carrying it out of the parallel lane.
    with pytest.raises(BaseException) as excinfo:
        await run.execute()

    # Assert AbortSignalError is present in the exception tree (WIRE assertion)
    def _contains_abort_signal_error(exc):
        if isinstance(exc, AbortSignalError):
            return True
        if isinstance(exc, BaseExceptionGroup):
            return any(_contains_abort_signal_error(e) for e in exc.exceptions)
        return False

    assert _contains_abort_signal_error(excinfo.value)
    assert run.report.status == "aborted"
    # Assert the innocent sibling lane's device was swept to safe state
    assert ("pump_1", "stop") in verbs(fake)
    assert run._ctx.occupancy.open_modes() == ()
