from lab_devices.experiment import PersistenceError
from lab_devices.experiment.errors import ExperimentRunError


def test_persistence_error_is_run_error():
    err = PersistenceError("disk config needs output_dir")
    assert isinstance(err, ExperimentRunError)
    assert "output_dir" in str(err)
