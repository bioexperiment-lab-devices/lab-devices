"""End-to-end coverage for the densitometer `read_temperature` measurement verb: it records
temperature into a stream via `status` (no optics), and — being channelless — runs while a
thermostat mode is open on the thermal channel."""

from lab_devices.experiment import ExperimentRun, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock, drive


def make_run(client, wf, **opt):
    return ExperimentRun(client, wf, options=RunOptions(clock=FakeClock(), **opt))


async def test_read_temperature_records_temperature_into_stream(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    # Re-add the densitometer with a canned `status` carrying temperature_c (read_temperature
    # reads temperature from status, not from the optics `measure` job).
    fake.add_device("densitometer_1", "densitometer", status={"state": "idle", "temperature_c": 36.98})
    wf = make_workflow(
        [{"measure": {"device": "densitometer_1", "verb": "read_temperature", "into": "temp"}}],
        streams={"temp": {"units": "degC"}},
    )
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())

    assert report.status == "completed"
    recorded = [e for e in report.log.events if e.kind == "measure_recorded"]
    assert len(recorded) == 1
    assert recorded[0].data == {"stream": "temp", "value": 36.98}
    # Read went over the `status` wire command — the optics `measure` never ran.
    called = verbs(fake)
    assert ("densitometer_1", "status") in called
    assert ("densitometer_1", "measure") not in called


async def test_read_temperature_runs_while_thermostat_open(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    fake.add_device("densitometer_1", "densitometer", status={"state": "idle", "temperature_c": 36.98})
    wf = make_workflow(
        [
            {
                "serial": {
                    "children": [
                        {
                            "command": {
                                "device": "densitometer_1",
                                "verb": "set_thermostat",
                                "params": {"enabled": True, "target_c": 37.0},
                            }
                        },
                        {
                            "measure": {
                                "device": "densitometer_1",
                                "verb": "read_temperature",
                                "into": "temp",
                            }
                        },
                    ]
                }
            }
        ],
        streams={"temp": {"units": "degC"}},
    )
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())

    # A channelless read never collides with the open thermostat mode on _THERMAL: had
    # read_temperature claimed the thermal channel, occupancy would raise here and the run fail.
    assert report.status == "completed"
    assert any(e.kind == "measure_recorded" for e in report.log.events)
