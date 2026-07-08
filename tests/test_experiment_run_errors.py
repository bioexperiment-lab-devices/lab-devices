# tests/test_experiment_run_errors.py
from lab_devices.experiment.errors import (
    BlockFailedError,
    ExperimentError,
    ExperimentRunError,
    FinalizeError,
    InvariantViolationError,
    RunAbortedError,
    UnsupportedPersistenceError,
)


def test_taxonomy():
    for cls in (
        BlockFailedError,
        InvariantViolationError,
        RunAbortedError,
        FinalizeError,
        UnsupportedPersistenceError,
    ):
        assert issubclass(cls, ExperimentRunError)
    assert issubclass(ExperimentRunError, ExperimentError)


def test_block_failed_carries_block_id():
    err = BlockFailedError("blocks[0].children[2]", "empty stream window")
    assert err.block_id == "blocks[0].children[2]"
    assert str(err) == "block blocks[0].children[2]: empty stream window"


def test_block_failed_cause_chain():
    cause = ValueError("boom")
    try:
        try:
            raise cause
        except ValueError as exc:
            raise BlockFailedError("blocks[1]", str(exc)) from exc
    except BlockFailedError as err:
        assert err.__cause__ is cause


def test_finalize_error_aggregates():
    errs = (RuntimeError("t1"), RuntimeError("t2"))
    err = FinalizeError(errs)
    assert err.errors == errs
    assert str(err) == "2 finalizer error(s); hardware may not be in a safe state"
