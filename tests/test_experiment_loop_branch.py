import pytest

from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.errors import BlockFailedError
from lab_devices.experiment.execute import execute_blocks
from lab_devices.experiment.run import ExperimentRun
from lab_devices.experiment.state import RunState, Stream
from tests.experiment_run_helpers import (
    add_standard_devices,
    make_workflow,
    role_devices,
    verbs,
)
from tests.fakeclock import FakeClock, drive


def make_ctx(client, workflow, *, clock=None):
    state = RunState()
    for name in workflow.streams:
        state.streams[name] = Stream()
    return RunContext(client=client, workflow=workflow, state=state,
                      options=RunOptions(clock=clock or FakeClock()),
                      role_devices=role_devices(workflow))


async def run_blocks(ctx):
    await drive(ctx.clock, execute_blocks(ctx.workflow.blocks, ctx))


STOP = {"command": {"device": "pump_1", "verb": "stop"}}


async def test_count_loop_runs_n_times(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"loop": {"count": 3, "body": [STOP]}}])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert verbs(fake) == [("pump_1", "stop")] * 3


async def test_count_loop_pace_is_a_floor(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"loop": {"count": 3, "pace": "60s", "body": [STOP]}}])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    # body is instant; two inter-iteration paces, no trailing pace after the last
    assert ctx.clock.now() == pytest.approx(120.0)


async def test_pace_never_cancels_overrunning_body(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"loop": {"count": 2, "pace": "5s",
                  "body": [{"wait": {"duration": "30s"}}, STOP]}},
    ])
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert len(verbs(fake)) == 2
    assert ctx.clock.now() == pytest.approx(60.0)  # overrun: next starts immediately


async def test_post_test_until_runs_body_then_checks(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"loop": {"check": "after", "until": "count(OD) >= 2",
                   "body": [{"measure": {"device": "densitometer_1", "verb": "measure",
                                         "into": "OD"}}]}}],
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert len(ctx.state.streams["OD"]) == 2  # >=1 iteration guaranteed; exits at 2


async def test_post_test_until_pace_is_floor_no_trailing(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"loop": {"check": "after", "until": "count(OD) >= 2", "pace": "60s",
                   "body": [{"measure": {"device": "densitometer_1", "verb": "measure",
                                         "into": "OD"}}]}}],
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert len(ctx.state.streams["OD"]) == 2
    # iter1 t=0 (until false -> pace to 60); iter2 t=60 (until true -> break, NO trailing pace)
    assert ctx.clock.now() == pytest.approx(60.0)


async def test_pre_test_until_pace_polls_between_checks(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"loop": {"check": "before", "until": "count(OD) >= 2", "pace": "30s",
                   "body": [{"measure": {"device": "densitometer_1", "verb": "measure",
                                         "into": "OD"}}]}}],
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert len(ctx.state.streams["OD"]) == 2
    # t=0 check(0>=2 F)+body->pace 30; t=30 check(1>=2 F)+body->pace 30; t=60 check(2>=2 T)->exit
    assert ctx.clock.now() == pytest.approx(60.0)


async def test_post_test_until_pace_runs_end_to_end_via_facade(fake_client):
    """Pins that the validator relaxation actually unlocked the until+pace path."""
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"loop": {"check": "after", "until": "count(OD) >= 2", "pace": "60s",
                   "body": [{"measure": {"device": "densitometer_1", "verb": "measure",
                                         "into": "OD"}}]}}],
        streams={"OD": {}},
    )
    run = ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    assert len(report.state.streams["OD"]) == 2


async def test_pre_test_until_can_run_zero_iterations(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"loop": {"check": "before", "until": "count(OD) >= 0", "body": [STOP]}}],
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert fake.calls == []  # already true: check-then-act skipped the body


async def test_pre_test_cold_start_fails_safe(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"loop": {"check": "before", "until": "mean(OD) >= 1.0", "body": [STOP]}}],
        streams={"OD": {}},
    )
    # NOTE: built via make_workflow (loader), not load_and_validate — the validator
    # would reject this cold-start read; the runtime backstop is what we pin here.
    ctx = make_ctx(client, wf)
    with pytest.raises(BlockFailedError, match="empty stream window"):
        await run_blocks(ctx)
    assert fake.calls == []


async def test_loop_body_gap_paces_iterations(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    # §15.2 pattern: gap_after on the LAST body child must pace iterations (spec §9)
    wf = make_workflow(
        [{"loop": {"count": 2, "body": [
            dict(STOP, gap_after="30s"),
        ]}}],
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert ctx.clock.now() == pytest.approx(60.0)  # gap after BOTH iterations


async def test_branch_then_else(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"branch": {"if": "count(OD) == 0",
                     "then": [{"command": {"device": "valve_1", "verb": "home",
                                           "params": {"position": 1}}}],
                     "else": [STOP]}},
         {"branch": {"if": "count(OD) > 0", "then": [STOP]}}],  # false, no else: skip
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert verbs(fake) == [("valve_1", "home")]


async def test_branch_else_taken(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"branch": {"if": "count(OD) > 0",  # false on the pre-created empty stream
                     "then": [{"command": {"device": "valve_1", "verb": "home",
                                           "params": {"position": 1}}}],
                     "else": [STOP]}}],
        streams={"OD": {}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert verbs(fake) == [("pump_1", "stop")]  # else ran, then skipped


async def test_group_ref_executes_body_inline(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"group_ref": {"name": "prime"}}, {"group_ref": {"name": "prime"}}],
        groups={"prime": {"body": [STOP]}},
    )
    ctx = make_ctx(client, wf)
    await run_blocks(ctx)
    assert verbs(fake) == [("pump_1", "stop")] * 2
