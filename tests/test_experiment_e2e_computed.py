from lab_devices.experiment import ExperimentRun, RunOptions
from tests.experiment_run_helpers import add_standard_devices, make_workflow
from tests.fakeclock import FakeClock, drive


def make_run(client, wf):
    return ExperimentRun(client, wf, options=RunOptions(clock=FakeClock()))


async def test_accumulator_and_recording_over_cycles(fake_client):
    """Seed c=0, then each cycle measure OD, compute a decay recursion, record c and a
    derived value into computed streams. Assert the recorded series and the final binding."""
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [
            {"compute": {"into": "c", "value": "0"}},
            {"loop": {"count": 3, "body": [
                {"measure": {"device": "densitometer_1", "verb": "measure", "into": "OD"}},
                {"compute": {"into": "c", "value": "c * 0.5 + 1"}},
                {"record": {"into": "c_series", "value": "c"}},
                {"record": {"into": "od_copy", "value": "last(OD)"}},
            ]}},
        ],
        streams={"OD": {"units": "AU"}, "c_series": {}, "od_copy": {}},
    )
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())

    assert report.status == "completed"
    c_series = [s.value for s in report.state.streams["c_series"].samples]
    assert c_series == [1.0, 1.5, 1.75]           # 0→1→1.5→1.75
    assert report.state.bindings["c"] == 1.75
    assert len(report.state.streams["od_copy"].samples) == 3


async def test_record_only_stream_is_precreated_empty(fake_client):
    """A record-only declared stream exists at count()==0 before its first write."""
    fake, client = fake_client
    add_standard_devices(fake)
    wf = make_workflow(
        [{"branch": {"if": "count(r_series) > 0", "then": [
            {"command": {"device": "pump_1", "verb": "stop"}}]}},
         {"record": {"into": "r_series", "value": "1.0"}}],
        streams={"r_series": {}},
    )
    run = make_run(client, wf)
    report = await drive(run._options.clock, run.execute())
    assert report.status == "completed"
    assert [s.value for s in report.state.streams["r_series"].samples] == [1.0]
