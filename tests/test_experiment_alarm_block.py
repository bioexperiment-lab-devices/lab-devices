from lab_devices.experiment import ExperimentRun, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow, verbs
from tests.fakeclock import FakeClock


def _run(client, wf):
    return ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))


async def test_alarm_fires_and_run_continues(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"alarm": {"if": "true", "message": "flagged"}},
        {"command": {"device": "pump_1", "verb": "stop"}},
    ])
    report = await _run(client, wf).execute()
    assert report.status == "completed"
    assert [a.message for a in report.alarms] == ["flagged"]
    assert "alarm_raised" in [e.kind for e in report.log.events]
    assert ("pump_1", "stop") in verbs(fake)


async def test_alarm_false_is_silent(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([{"alarm": {"if": "false", "message": "nope"}}])
    report = await _run(client, wf).execute()
    assert report.alarms == ()
    assert "alarm_raised" not in [e.kind for e in report.log.events]


async def test_alarm_is_stateless_fires_each_cycle(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"loop": {"count": 3, "body": [{"alarm": {"if": "true", "message": "tick"}}]}},
    ])
    report = await _run(client, wf).execute()
    assert len(report.alarms) == 3


async def test_alarm_latch_idiom_fires_once(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow([
        {"compute": {"into": "alarmed", "value": "false"}},
        {"loop": {"count": 3, "body": [
            {"alarm": {"if": "not alarmed", "message": "once"}},
            {"compute": {"into": "alarmed", "value": "true"}},
        ]}},
    ])
    report = await _run(client, wf).execute()
    assert len(report.alarms) == 1
