"""Duration/count slots accept expressions typed number<s> / int, resolved at entry
(design 2026-07-21 §6, Engine C Tasks 2-3)."""

from __future__ import annotations

from lab_devices.experiment import ExperimentRun, RunOptions
from lab_devices.experiment.validate import validate
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.experiment_validate_helpers import diags, wf
from tests.fakeclock import FakeClock, drive


def _run(client, workflow):
    return ExperimentRun(client, workflow, options=RunOptions(clock=FakeClock()))


# --- validate: duration/count slot typing ---


def test_wait_duration_bare_number_is_a_unit_error() -> None:
    assert any(x.category == "units" for x in diags(wf([{"wait": {"duration": "5"}}])))


def test_wait_duration_literal_is_clean() -> None:
    validate(wf([{"wait": {"duration": "5min"}}]))  # must not raise


def test_wait_duration_expression_is_clean() -> None:
    # pause_min (unitless float input) * 1min (number<s>) -> number<s>.
    validate(wf([
        {"operator_input": {"name": "pause_min", "type": "float"}},
        {"wait": {"duration": "pause_min * 1min"}},
    ]))


def test_loop_count_float_expression_is_rejected() -> None:
    d = diags(wf([
        {"compute": {"into": "n", "value": "1.5"}},
        {"loop": {"count": "n", "body": [{"wait": {"duration": "1s"}}]}},
    ]))
    assert any(x.category == "type" for x in d)


def test_loop_count_int_expression_is_clean() -> None:
    validate(wf([
        {"compute": {"into": "n", "value": "1 + 2"}},
        {"loop": {"count": "n", "body": [{"wait": {"duration": "1s"}}]}},
    ]))


# --- runtime: slots resolve expressions at entry ---


async def test_wait_duration_from_a_binding_completes(fake_client) -> None:
    fake, client = fake_client
    add_standard_devices(fake)
    workflow = make_workflow([
        {"compute": {"into": "pause_s", "value": "2s"}},  # number<s>
        {"wait": {"duration": "pause_s"}},
    ])
    run = _run(client, workflow)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"


async def test_loop_count_from_a_binding_runs_that_many_times(fake_client) -> None:
    fake, client = fake_client
    add_standard_devices(fake)
    workflow = make_workflow(
        [
            {"compute": {"into": "cycles", "value": "1 + 2"}},
            {"loop": {"count": "cycles", "body": [
                {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
            ]}},
        ],
        streams={"OD": {"units": "AU"}},
    )
    run = _run(client, workflow)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    assert len(report.state.streams["OD"].samples) == 3
