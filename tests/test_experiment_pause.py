import asyncio

from lab_devices.experiment import ExperimentRun, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


def start_run(client, wf, **opt):
    run = ExperimentRun(client, wf, options=RunOptions(clock=FakeClock(), **opt))
    task = asyncio.ensure_future(run.execute())
    return run, run._options.clock, task


async def test_pause_quiesces_while_inflight_job_finishes(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
        {"command": {"device": "pump_2", "verb": "stop"}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    assert verbs(fake) == [("pump_1", "dispense")]  # in flight, held

    run.pause()
    job_id = next(iter(fake.jobs))
    fake.complete_job(job_id)          # hardware finishes WHILE paused
    await clock.advance(5.0)           # poll sleeps elapse; job wait completes
    finished = [e for e in run._ctx.options.log_sink.events if e.kind == "block_finished"]
    assert any(e.block_id == "blocks[0]" for e in finished)  # in-flight block completed
    assert ("pump_2", "stop") not in verbs(fake)  # but nothing NEW dispatched

    run.resume()
    report = await drive(clock, task)
    assert report.status == "completed"
    assert ("pump_2", "stop") in verbs(fake)
    kinds = [e.kind for e in report.log.events]
    assert kinds.index("paused") < kinds.index("resumed")


async def test_pause_leaves_open_modes_running(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"wait": {"duration": "60s"}},
        {"command": {"device": "pump_2", "verb": "stop"}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    assert len(run._ctx.occupancy.open_modes()) == 1  # rotate is open

    run.pause()
    await clock.advance(60.0)  # the wait elapses during pause; next block stays gated
    assert len(run._ctx.occupancy.open_modes()) == 1  # STILL open: pause never tears down
    assert ("pump_2", "stop") not in verbs(fake)

    run.resume()
    report = await drive(clock, task)
    assert report.status == "completed"
    assert run._ctx.occupancy.open_modes() == ()


async def test_pause_gates_loop_iteration_top(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"loop": {"count": 3, "body": [
            {"command": {"device": "pump_1", "verb": "stop"}},
            {"wait": {"duration": "10s"}},
        ]}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    assert verbs(fake) == [("pump_1", "stop")]  # iteration 1 dispatched, in its wait

    run.pause()
    await clock.advance(10.0)  # iteration 1 body completes; iteration 2 gated at loop top
    await clock.settle()
    assert verbs(fake) == [("pump_1", "stop")]

    run.resume()
    report = await drive(clock, task)
    assert report.status == "completed"
    assert [v for v in verbs(fake) if v == ("pump_1", "stop")][:3] == [("pump_1", "stop")] * 3


async def test_pause_before_execute_gates_first_block(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"command": {"device": "pump_1", "verb": "stop"}}])
    run = ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))
    run.pause()  # before execute(): gate cleared silently (no clock available yet)
    task = asyncio.ensure_future(run.execute())
    clock = run._options.clock
    await clock.settle()
    assert fake.calls == []  # first block never dispatched
    run.resume()
    report = await drive(clock, task)
    assert report.status == "completed"


async def test_pause_resume_idempotent_events(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}},
    ])
    run, clock, task = start_run(client, wf)
    await clock.settle()
    run.pause()
    run.pause()   # no second event
    run.resume()
    run.resume()  # no second event
    fake.complete_job(next(iter(fake.jobs)))
    await drive(clock, task)
    kinds = [e.kind for e in run.report.log.events]
    assert kinds.count("paused") == 1 and kinds.count("resumed") == 1
