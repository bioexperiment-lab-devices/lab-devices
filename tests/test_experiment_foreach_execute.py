"""Increment 7 Task 4: the executor runs the EXPANDED workflow (design 2026-07-15 SS4.4).

`ExperimentRun.__init__` must expand `for_each` / parametrized `group_ref` away before
`assign_block_ids` and execution, so the executor only ever walks a concrete tree: no
`ForEach` node, no parametrized `group_ref` reaches `execute_blocks`. This is also what
makes the `AssertionError` guard added in execute.py's `_execute_inner` (Increment 7 Task 1,
for the `ForEach` case) genuinely unreachable in a full run.
"""

from lab_devices.experiment import ExperimentRun, RunOptions
from lab_devices.experiment.serialize import workflow_from_dict
from tests.fakeclock import FakeClock, drive


async def test_for_each_drives_three_distinct_devices(fake_client):
    """A top-level for_each inside a parallel block splices into three concrete measure
    blocks, one per device/stream — proving expansion, not just validation, reaches
    execution."""
    fake, client = fake_client
    for i in (1, 2, 3):
        fake.add_device(f"densitometer_{i}", "densitometer")
    workflow = workflow_from_dict({
        "schema_version": 1,
        "streams": {"od_1": {}, "od_2": {}, "od_3": {}},
        "blocks": [{"parallel": {"children": [
            {"for_each": {"var": "t", "in": [1, 2, 3],
                          "body": [{"measure": {"device": "densitometer_{t}",
                                                "verb": "measure", "into": "od_{t}"}}]}}]}}],
    })
    clock = FakeClock()
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())

    assert report.status == "completed"
    for i in (1, 2, 3):
        assert len(report.state.streams[f"od_{i}"].samples) == 1


async def test_parametrized_group_per_tube_accumulator_does_not_cross_contaminate(fake_client):
    """A parametrized group_ref, invoked once per for_each iteration, inlines to a distinct
    `compute` per tube — proving group inlining plus for_each interpolation both survive to
    the executor with no cross-contamination between iterations."""
    fake, client = fake_client
    workflow = workflow_from_dict({
        "schema_version": 1,
        "streams": {},
        "groups": {"seed": {"params": ["t"],
                            "body": [{"compute": {"into": "c_{t}", "value": "{t} * 10"}}]}},
        "blocks": [{"for_each": {"var": "t", "in": [1, 2, 3],
                    "body": [{"group_ref": {"name": "seed", "args": {"t": "{t}"}}}]}}],
    })
    clock = FakeClock()
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    report = await drive(clock, run.execute())

    assert report.status == "completed"
    assert report.state.bindings["c_1"] == 10
    assert report.state.bindings["c_2"] == 20
    assert report.state.bindings["c_3"] == 30


async def test_expanded_block_ids_are_positional_and_stable(fake_client):
    """assign_block_ids runs AFTER expansion, so ids are positional over the EXPANDED
    children, not the authored for_each node."""
    fake, client = fake_client
    for i in (1, 2):
        fake.add_device(f"densitometer_{i}", "densitometer")
    workflow = workflow_from_dict({
        "schema_version": 1, "streams": {"od_1": {}, "od_2": {}},
        "blocks": [{"serial": {"children": [
            {"for_each": {"var": "t", "in": [1, 2],
                          "body": [{"measure": {"device": "densitometer_{t}",
                                                "verb": "measure", "into": "od_{t}"}}]}}]}}],
    })
    clock = FakeClock()
    run = ExperimentRun(client, workflow, options=RunOptions(clock=clock))
    ids = [b.id for b in run._workflow.blocks[0].children]  # type: ignore[attr-defined]
    assert ids == ["blocks[0].children[0]", "blocks[0].children[1]"]

    report = await drive(clock, run.execute())
    assert report.status == "completed"
