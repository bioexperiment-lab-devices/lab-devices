import asyncio

import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.errors import (
    PersistenceError,
    UnknownRoleError,
    WorkflowLoadError,
)
from lab_devices.experiment.execute import _dispatch_action
from lab_devices.experiment.run import ExperimentRun, _resolve_roles
from lab_devices.experiment.state import RunState
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.fakeclock import FakeClock, drive


def make_ctx(client, role_devices):
    return RunContext(
        client=client,
        workflow=make_workflow([]),
        state=RunState(),
        options=RunOptions(clock=FakeClock()),
        role_devices=dict(role_devices),
    )


def test_run_options_carries_a_role_mapping():
    options = RunOptions(role_mapping={"od_meter": "densitometer_1"})
    assert options.role_mapping == {"od_meter": "densitometer_1"}
    assert RunOptions().role_mapping == {}


async def test_context_device_resolves_a_role_to_its_physical_handle(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    ctx = make_ctx(client, {"od_meter": "densitometer_1"})
    device = ctx.device("od_meter")
    assert device.id == "densitometer_1"
    assert set(ctx.devices) == {"od_meter"}   # cached under the ROLE
    assert ctx.device("od_meter") is device   # one handle per role


async def test_context_device_raises_for_an_unmapped_role(fake_client):
    _, client = fake_client
    ctx = make_ctx(client, {})
    with pytest.raises(KeyError):
        ctx.device("od_meter")


TWO_PUMPS = {"left": {"type": "pump"}, "right": {"type": "pump"}}
STOP_BOTH = [{"command": {"device": "left", "verb": "stop"}},
             {"command": {"device": "right", "verb": "stop"}}]


def test_resolve_roles_prefers_the_mapping_over_the_declaration():
    w = make_workflow(STOP_BOTH, roles={"left": {"type": "pump", "device": "pump_1"},
                                        "right": {"type": "pump", "device": "pump_2"}})
    resolved = _resolve_roles(w, {"left": "valve_1"})
    assert resolved == {"left": "valve_1", "right": "pump_2"}


def test_resolve_roles_rejects_an_unbound_role():
    w = make_workflow(STOP_BOTH, roles=TWO_PUMPS)
    with pytest.raises(WorkflowLoadError, match="role 'left' is not bound to a device"):
        _resolve_roles(w, {"right": "pump_2"})


def test_resolve_roles_rejects_a_non_injective_mapping():
    w = make_workflow(STOP_BOTH, roles=TWO_PUMPS)
    with pytest.raises(WorkflowLoadError, match="must be injective"):
        _resolve_roles(w, {"left": "pump_1", "right": "pump_1"})


def test_resolve_roles_rejects_a_mapping_for_an_unknown_role():
    w = make_workflow(STOP_BOTH, roles=TWO_PUMPS)
    with pytest.raises(UnknownRoleError, match="ghost"):
        _resolve_roles(w, {"left": "pump_1", "right": "pump_2", "ghost": "valve_1"})


async def test_run_construction_rejects_a_non_injective_mapping(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(STOP_BOTH, roles=TWO_PUMPS)
    options = RunOptions(clock=FakeClock(),
                         role_mapping={"left": "pump_1", "right": "pump_1"})
    with pytest.raises(WorkflowLoadError, match="must be injective"):
        ExperimentRun(client, w, options=options)
    assert fake.calls == []  # nothing reached the wire


async def test_run_construction_accepts_distinct_devices(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(STOP_BOTH, roles=TWO_PUMPS)
    options = RunOptions(clock=FakeClock(),
                         role_mapping={"left": "pump_1", "right": "pump_2"})
    run = ExperimentRun(client, w, options=options)
    assert run._ctx.role_devices == {"left": "pump_1", "right": "pump_2"}


async def test_report_records_the_role_mapping_once(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(
        [{"command": {"device": "left", "verb": "stop"}}],
        roles={"left": {"type": "pump", "device": "pump_1"}},
    )
    clock = FakeClock()
    run = ExperimentRun(client, w, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())
    assert report.status == "completed"
    assert report.role_devices == {"left": "pump_1"}
    payloads = [e.data for e in report.log.events if "device" in e.data]
    assert payloads and all(p["device"] == "left" for p in payloads)


async def test_failed_report_also_records_the_mapping(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(
        [{"command": {"device": "left", "verb": "stop"}}],
        roles={"left": {"type": "pump", "device": "pump_1"}},
        persistence={"default": "disk", "format": "jsonl"},
    )
    run = ExperimentRun(client, w, options=RunOptions(clock=FakeClock()))
    with pytest.raises(PersistenceError):
        await run.execute()
    assert run.report is not None
    assert run.report.role_devices == {"left": "pump_1"}


# A role name that deliberately does NOT decode to a device type under the deleted
# `rsplit("_", 1)` bridge: it would have yielded 'culture', which is not a device type at all.
OD_ROLES = {"culture_vessel": {"type": "densitometer", "device": "densitometer_1"}}


async def test_verbs_resolve_through_the_role_declaration(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(
        [{"measure": {"device": "culture_vessel", "verb": "measure", "into": "OD"}}],
        streams={"OD": {"units": "AU"}},
        roles=OD_ROLES,
    )
    clock = FakeClock()
    run = ExperimentRun(client, w, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())
    assert report.status == "completed"
    assert len(report.state.streams["OD"]) == 1  # result_field came from the registry


async def test_finalizer_sweeps_by_declared_type_not_by_id(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(
        [{"measure": {"device": "culture_vessel", "verb": "measure", "into": "OD"}}],
        streams={"OD": {}},
        roles=OD_ROLES,
    )
    clock = FakeClock()
    run = ExperimentRun(client, w, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())
    assert report.status == "completed"
    swept = [(dev, cmd) for dev, cmd, _ in fake.calls if dev == "densitometer_1"]
    assert ("densitometer_1", "stop_monitoring") in swept
    assert ("densitometer_1", "set_led") in swept


async def test_every_engine_structure_keys_on_the_role_name(fake_client):
    """The §5.2 invariant, pinned. If a later change makes this fail, the change is
    wrong: locks, occupancy, touched, in_flight and event payloads all key on the ROLE,
    and `ctx.device(role)` is the single site where a physical id appears."""
    fake, client = fake_client
    add_standard_devices(fake)
    w = make_workflow(
        [{"measure": {"device": "culture_vessel", "verb": "measure", "into": "OD"}}],
        streams={"OD": {}},
        roles=OD_ROLES,
    )
    clock = FakeClock()
    run = ExperimentRun(client, w, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())
    assert report.status == "completed"

    ctx = run._ctx
    assert list(ctx.touched) == ["culture_vessel"]
    assert set(ctx.locks) == {"culture_vessel"}
    assert set(ctx.devices) == {"culture_vessel"}   # handle cached under the role
    assert ctx.occupancy.busy_devices() == set()    # released, by role key
    assert ctx.role_devices == {"culture_vessel": "densitometer_1"}

    payloads = [e.data["device"] for e in report.log.events if "device" in e.data]
    assert payloads and set(payloads) == {"culture_vessel"}

    # ...and the wire, and only the wire, saw the physical id.
    assert ("densitometer_1", "measure") in [(d, c) for d, c, _ in fake.calls]
    assert not any(d == "culture_vessel" for d, _c, _p in fake.calls)


async def test_occupancy_slots_key_on_the_role_name(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.hold_job("dispense")
    w = make_workflow([], roles={"feed": {"type": "pump", "device": "pump_2"}})
    ctx = RunContext(
        client=client, workflow=w, state=RunState(),
        options=RunOptions(clock=FakeClock()),
        role_devices={"feed": "pump_2"},
    )
    block = B.Command(device="feed", verb="dispense", params={"volume_ml": 1.0}, id="b0")
    task = asyncio.ensure_future(_dispatch_action(block, ctx, []))
    await ctx.options.clock.settle()
    assert ctx.occupancy.busy_devices() == {"feed"}
    assert ctx.occupancy.is_busy("feed") and not ctx.occupancy.is_busy("pump_2")
    task.cancel()
    try:
        await task
    except BaseException:
        pass
