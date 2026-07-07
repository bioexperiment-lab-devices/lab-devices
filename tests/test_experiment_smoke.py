from lab_devices.experiment.errors import (
    ExperimentError,
    UnknownVerbError,
    WorkflowLoadError,
)


def test_error_hierarchy():
    assert issubclass(WorkflowLoadError, ExperimentError)
    assert issubclass(UnknownVerbError, WorkflowLoadError)
    err = UnknownVerbError("nope")
    assert isinstance(err, ExperimentError)
    assert str(err) == "nope"
