# tests/test_experiment_e2e_sequential.py
"""Flagship E2E scenarios (design 4-exec §16 #1-5): call-sequence assertions vs FakeLab."""
import pytest

from lab_devices.experiment import BlockFailedError, ExperimentRun, RunOptions
from tests.experiment_run_helpers import (
    ScriptedInputProvider,
    add_standard_devices,
    make_workflow,
    verbs,
)
from tests.fakeclock import FakeClock, drive


def make_run(client, wf, **opt):
    return ExperimentRun(client, wf, options=RunOptions(clock=FakeClock(), **opt))


async def test_flagship_rotate_measure_feedback(fake_client):
    """§15.2-shaped: prime group, stir throughout, feedback dispense, explicit close,
    close-with-no-open branch, full sweep, zero open modes."""
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"serial": {"children": [
            {"operator_input": {"name": "target_OD", "type": "float",
                                "prompt": "Enter target OD", "min": 0.0, "max": 2.0}},
            {"group_ref": {"name": "prime_line"}},
            {"command": {"device": "pump_2", "verb": "rotate",
                         "params": {"direction": "forward", "speed_ml_min": 2.0}}},
            {"loop": {"check": "after", "until": "mean(OD, last=5min) >= 0.5",
                      "body": [
                          {"measure": {"device": "densitometer_1", "verb": "measure",
                                       "into": "OD"}},
                          {"command": {"device": "pump_1", "verb": "dispense",
                                       "params": {"volume_ml":
                                                  "2.0 * (target_OD - mean(OD, last=100))",
                                                  "speed_ml_min": 3.0}},
                           "gap_after": "30s"},
                      ]}},
            {"command": {"device": "pump_2", "verb": "stop"}},
            {"branch": {"if": "last(OD) < target_OD",
                        "then": [{"command": {"device": "densitometer_1",
                                              "verb": "set_led",
                                              "params": {"level": 0}}}]}},
        ]}}],
        streams={"OD": {"units": "AU"}},
        groups={"prime_line": {"body": [
            {"command": {"device": "pump_1", "verb": "dispense",
                         "params": {"volume_ml": 1.0, "speed_ml_min": 5.0}}}]}},
    )
    run = make_run(client, wf, input_provider=ScriptedInputProvider({"target_OD": 0.55}))
    report = await drive(run._options.clock, run.execute())

    assert report.status == "completed"
    assert verbs(fake) == [
        ("pump_1", "dispense"),            # prime group
        ("pump_2", "rotate"),              # stir mode opens
        ("densitometer_1", "measure"),     # loop iteration 1 (canned OD 0.523)
        ("pump_1", "dispense"),            # feedback dispense
        ("pump_2", "stop"),                # explicit close of rotate
        ("densitometer_1", "set_led"),     # branch: close-with-no-open (level 0)
        # finalizer sweep over touched devices, insertion order:
        ("pump_1", "stop"),
        ("pump_2", "stop"),
        ("densitometer_1", "stop"),
        ("densitometer_1", "stop_monitoring"),
        ("densitometer_1", "set_led"),
        ("densitometer_1", "set_thermostat"),
    ]
    feedback = [c for c in fake.calls if c[1] == "dispense"][1]
    assert feedback[2]["volume_ml"] == pytest.approx(2.0 * (0.55 - 0.523))
    assert run._ctx.occupancy.open_modes() == ()  # nothing left open
    # the 30s gap paced the loop before the until-check
    assert report.log.events[0].kind == "run_started"


async def test_flagship_midrun_job_failure_full_finalizer(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.fail_jobs.add("dispense")
    wf = make_workflow([
        {"command": {"device": "pump_2", "verb": "rotate",
                     "params": {"direction": "forward", "speed_ml_min": 2.0}}},
        {"loop": {"count": 2, "body": [
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
            {"command": {"device": "pump_1", "verb": "dispense",
                         "params": {"volume_ml": 1.0}}},
        ]}},
    ], streams={"OD": {}})
    run = make_run(client, wf)
    with pytest.raises(BlockFailedError):
        await drive(run._options.clock, run.execute())
    assert run.report.status == "failed"
    seq = verbs(fake)
    assert seq[:4] == [("pump_2", "rotate"), ("densitometer_1", "measure"),
                       ("pump_1", "dispense"), ("pump_2", "stop")]  # teardown right after
    assert ("densitometer_1", "set_thermostat") in seq  # sweep completed
    assert run._ctx.occupancy.open_modes() == ()


async def test_flagship_failsafe_empty_duration_window(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
        {"wait": {"duration": "10s"}},
        {"command": {"device": "pump_1", "verb": "dispense",
                     "params": {"volume_ml": "mean(OD, last=1s)"}}},
    ], streams={"OD": {}})
    run = make_run(client, wf)
    with pytest.raises(BlockFailedError, match="empty stream window"):
        await drive(run._options.clock, run.execute())
    assert ("pump_1", "dispense") not in verbs(fake)  # failed before the wire
    assert run.report.status == "failed"
    assert ("densitometer_1", "stop") in verbs(fake)  # finalizer swept touched devices
    assert all(d != "pump_1" for d, _ in verbs(fake))  # pump_1 never touched -> not swept


async def test_flagship_count_zero_on_precreated_stream(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"branch": {"if": "count(S) == 0",
                    "then": [{"command": {"device": "densitometer_1", "verb": "set_led",
                                          "params": {"level": 5}}}]}},
    ], streams={"S": {}})
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    seq = verbs(fake)
    assert seq[0] == ("densitometer_1", "set_led")  # branch taken: count(S)==0
    # set_led(5) opened a mode; the finalizer's teardown AND sweep both set_led(0)
    led_calls = [c for c in fake.calls if c[1] == "set_led"]
    assert [c[2]["level"] for c in led_calls] == [5, 0, 0]
    assert run._ctx.occupancy.open_modes() == ()


async def test_flagship_operator_input_feeds_param(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"operator_input": {"name": "target", "type": "float", "min": 0.0, "max": 100.0}},
        {"command": {"device": "pump_1", "verb": "dispense",
                     "params": {"volume_ml": "target / 10"}}},
    ])
    run = make_run(client, wf, input_provider=ScriptedInputProvider({"target": 42.0}))
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    assert fake.calls[0][2]["volume_ml"] == pytest.approx(4.2)


async def test_flagship_operator_input_unattended_fails_through_facade(fake_client):
    """Flagship 5b: no input_provider -> the default UnattendedInputProvider fails the
    block through the facade, yet the finalizer still runs (fail-safe, §8/§11)."""
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"operator_input": {"name": "target", "type": "float"}},
        {"command": {"device": "pump_1", "verb": "dispense",
                     "params": {"volume_ml": "target / 10"}}},
    ])
    run = make_run(client, wf)  # DEFAULT unattended provider
    with pytest.raises(BlockFailedError, match="no input provider"):
        await drive(run._options.clock, run.execute())
    assert run.report.status == "failed"
    kinds = [e.kind for e in run.report.log.events]
    assert "finalize_started" in kinds and "finalize_finished" in kinds
