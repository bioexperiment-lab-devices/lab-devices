from lab_devices.experiment import blocks as B
from lab_devices.experiment.context import RunContext, RunOptions
from lab_devices.experiment.execute import _run_measure
from lab_devices.experiment.state import RunState, Sample, Stream
from lab_devices.experiment.workflow import Workflow
from tests.experiment_run_helpers import add_standard_devices
from tests.fakeclock import FakeClock, drive


class _RecordingStreamSink:
    def __init__(self) -> None:
        self.samples: list[Sample] = []

    def write(self, sample: Sample) -> None:
        self.samples.append(sample)

    def flush(self) -> None: ...
    def close(self) -> None: ...


async def test_measure_writes_same_timestamp_to_stream_sink(fake_client):
    fake, client = fake_client
    add_standard_devices(fake)
    clock = FakeClock()
    state = RunState()
    state.streams["OD"] = Stream()
    sink = _RecordingStreamSink()
    ctx = RunContext(client=client, workflow=Workflow(schema_version=1), state=state,
                     options=RunOptions(clock=clock))
    ctx.stream_sinks = {"OD": sink}
    block = B.Measure(device="densitometer_1", verb="measure", into="OD")
    block.id = "blocks[0]"
    await drive(clock, _run_measure(block, ctx))
    assert len(sink.samples) == 1
    # the persisted sample timestamp equals the in-memory sample timestamp exactly
    assert sink.samples[0].timestamp == state.streams["OD"].samples[0].timestamp
    assert sink.samples[0].value == state.streams["OD"].samples[0].value
