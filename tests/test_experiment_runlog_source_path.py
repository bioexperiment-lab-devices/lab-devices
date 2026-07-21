"""Integration test: the engine attaches the authored `source_path` to every block-scoped
run event, via `expand_workflow_traced` + `RunContext.source_map` (design 2026-07-16 §5.3,
Increment: human-readable block names in the run log, Task 2).

Model: `tests/test_experiment_runlog_inputs.py` for the runlog/event pattern,
`tests/test_experiment_run_facade.py` and `tests/test_experiment_foreach_execute.py` for the
`ExperimentRun` + `FakeClock` + `fake_client` harness.
"""

from lab_devices.experiment import ExperimentRun, RunOptions
from lab_devices.experiment.runlog import InMemoryRunLog
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.fakeclock import FakeClock, drive


async def test_source_path_maps_expanded_events_to_authored_blocks(fake_client):
    """A workflow whose top-level blocks are:
      [0] for_each over 2 rows, body = [ a single command block ]
      [1] a plain command block
    expands to three concrete blocks (two for_each copies + the shifted plain block). Every
    block_started event must carry the AUTHORED structural path, not the expanded one."""
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"for_each": {"vars": [{"name": "t", "kind": "int"}],
                      "in": [{"t": 1}, {"t": 2}],
                      "body": [{"command": {"device": "pump_1", "verb": "stop"}}]}},
        {"command": {"device": "pump_2", "verb": "stop"}},
    ])
    sink = InMemoryRunLog()
    clock = FakeClock()
    run = ExperimentRun(client, wf, options=RunOptions(clock=clock, log_sink=sink))
    report = await drive(clock, run.execute())
    assert report.status == "completed"

    by_kind: dict[str, list] = {}
    for e in sink.events:
        by_kind.setdefault(e.kind, []).append(e)

    started = by_kind["block_started"]
    # Two for_each copies BOTH trace to the single authored body block (many-to-one):
    for_each_copies = [e for e in started if e.source_path == "blocks[0].body[0]"]
    assert len(for_each_copies) == 2

    # The plain block (authored blocks[1], expanded blocks[2]) traces to its authored path
    # -- this is the index-shift risk: naive block_id-as-authored-path would read blocks[2].
    assert any(e.source_path == "blocks[1]" for e in started)

    # Lifecycle events (block_id=None) must never get a source_path.
    assert by_kind["run_started"]
    assert all(e.source_path is None for e in by_kind["run_started"])
