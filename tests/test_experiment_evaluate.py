import pytest

from lab_devices.experiment.errors import EvaluationError
from lab_devices.experiment.evaluate import evaluate, resolve
from lab_devices.experiment.expr import parse_expression
from lab_devices.experiment.state import RunState, Stream


def ev(text, state=None, now=0.0):
    return evaluate(parse_expression(text), state if state is not None else RunState(), now)


def _od_state():
    state = RunState()
    for t, v in [(0.0, 0.4), (10.0, 0.5), (20.0, 0.6), (30.0, 0.7)]:
        state.record("OD", t, v)
    return state


def test_arithmetic():
    assert ev("1 + 2 * 3") == 7
    assert ev("(1 + 2) * 3") == 9
    assert ev("7 / 2") == 3.5
    assert ev("-4 + 1") == -3


def test_int_and_float_results():
    assert ev("2 + 3") == 5
    assert isinstance(ev("2 + 3"), int)
    assert isinstance(ev("2.0 + 3"), float)


def test_division_by_zero_raises():
    with pytest.raises(EvaluationError, match="division by zero"):
        ev("1 / 0")
    with pytest.raises(EvaluationError, match="division by zero"):
        ev("1 / (2 - 2)")


def test_huge_int_arithmetic_raises_overflow():
    with pytest.raises(EvaluationError, match="overflow"):
        ev("9" * 400 + " / 3")
    with pytest.raises(EvaluationError, match="overflow"):
        ev("9" * 400 + " + 1.5")


def test_finite_literals_overflowing_to_inf_raise():
    # Both literals are finite floats; the product overflows float range.
    with pytest.raises(EvaluationError, match="overflow"):
        ev("1" + "0" * 308 + ".0 * 10")


def test_non_finite_binding_raises_instead_of_comparing():
    nan_state = RunState()
    nan_state.bind("x", float("nan"))
    with pytest.raises(EvaluationError, match="non-finite"):
        ev("x < 1", nan_state)

    inf_state = RunState()
    inf_state.bind("x", float("inf"))
    with pytest.raises(EvaluationError, match="non-finite"):
        ev("x < 1", inf_state)


def test_stat_over_stream_with_inf_raises():
    state = RunState()
    state.record("OD", 0.0, float("inf"))
    with pytest.raises(EvaluationError, match="non-finite"):
        ev("mean(OD)", state)
    with pytest.raises(EvaluationError, match="non-finite"):
        ev("last(OD)", state)


def test_comparisons():
    assert ev("1 < 2") is True
    assert ev("2 <= 2") is True
    assert ev("3 > 4") is False
    assert ev("4 >= 5") is False
    assert ev("1 == 1.0") is True
    assert ev("1 != 2") is True


def test_boolean_operators():
    assert ev("true and false") is False
    assert ev("true or false") is True
    assert ev("not true") is False
    assert ev("not 1 > 2") is True


def test_bool_equality():
    assert ev("true == true") is True
    assert ev("true != false") is True


def test_bindings():
    state = RunState()
    state.bind("target_OD", 0.8)
    assert ev("target_OD * 2", state) == pytest.approx(1.6)


def test_unbound_binding_raises():
    with pytest.raises(EvaluationError, match="unbound binding 'target_OD'"):
        ev("target_OD + 1")


def test_string_binding_rejected_in_numeric_context():
    # A string binding is fine in a string comparison (design §6) but still refused where a
    # number is required or in a mixed comparison.
    state = RunState()
    state.bind("mode", "fast")
    with pytest.raises(EvaluationError, match="string"):
        ev("mode == 1", state)  # string vs number
    with pytest.raises(EvaluationError, match="number"):
        ev("mode + 1", state)  # arithmetic on a string
    assert ev("mode == 'fast'", state) is True


@pytest.mark.parametrize("bad", ["1 + true", "true < false", "not 3", "1 and true", "1 == true"])
def test_type_mismatches_raise(bad):
    with pytest.raises(EvaluationError):
        ev(bad)


def test_stats_over_all():
    state = _od_state()
    assert ev("last(OD)", state, now=30.0) == 0.7
    assert ev("mean(OD)", state, now=30.0) == pytest.approx(0.55)
    assert ev("min(OD)", state, now=30.0) == 0.4
    assert ev("max(OD)", state, now=30.0) == 0.7
    assert ev("count(OD)", state, now=30.0) == 4


def test_sample_window_takes_most_recent():
    state = _od_state()
    assert ev("mean(OD, last=2)", state, now=30.0) == pytest.approx(0.65)


def test_sample_window_is_a_cap_not_a_minimum():
    # Design §15.2 evaluates mean(OD, last=100) right after the first measurement:
    # last=N means "up to the N most recent samples", so 4 samples is fine.
    state = _od_state()
    assert ev("mean(OD, last=100)", state, now=30.0) == pytest.approx(0.55)


def test_duration_window_is_relative_to_now():
    state = _od_state()
    assert ev("mean(OD, last=15s)", state, now=30.0) == pytest.approx(0.65)
    assert ev("count(OD, last=1min)", state, now=30.0) == 4


def test_duration_window_boundary_is_inclusive():
    state = _od_state()
    assert ev("count(OD, last=10s)", state, now=30.0) == 2


def test_stale_stream_fails_fresh_window():
    state = _od_state()
    with pytest.raises(EvaluationError, match="empty stream window"):
        ev("last(OD, last=5s)", state, now=120.0)


@pytest.mark.parametrize("fn", ["last", "mean", "min", "max"])
def test_empty_window_raises_for_value_stats(fn):
    state = RunState()
    state.streams["OD"] = Stream()
    with pytest.raises(EvaluationError, match="empty stream window"):
        ev(f"{fn}(OD)", state)


def test_count_over_empty_window_is_zero_not_missing():
    state = RunState()
    state.streams["OD"] = Stream()
    assert ev("count(OD)", state) == 0


def test_unknown_stream_raises():
    with pytest.raises(EvaluationError, match="unknown stream 'OD'"):
        ev("count(OD)")


def test_short_circuit_and_enables_count_guard():
    state = RunState()
    state.streams["OD"] = Stream()
    assert ev("count(OD) >= 1 and mean(OD) > 0.5", state) is False


def test_short_circuit_or():
    state = RunState()
    state.streams["OD"] = Stream()
    assert ev("count(OD) == 0 or mean(OD) > 0.5", state) is True


def test_left_operand_of_and_still_fails_on_missing_data():
    state = RunState()
    state.streams["OD"] = Stream()
    with pytest.raises(EvaluationError):
        ev("mean(OD) > 0.5 and count(OD) >= 1", state)


def test_resolve_passes_literals_through():
    state = RunState()
    assert resolve(3.5, state, now=0.0) == 3.5
    assert resolve(7, state, now=0.0) == 7
    assert resolve(True, state, now=0.0) is True


def test_resolve_parses_and_evaluates_strings():
    state = _od_state()
    state.bind("target_OD", 0.8)
    volume = resolve("2.0 * (target_OD - mean(OD, last=100))", state, now=30.0)
    assert volume == pytest.approx(2.0 * (0.8 - 0.55))
    assert resolve("mean(OD, last=5min) >= target_OD", state, now=30.0) is False


def test_non_finite_binding_rejected():
    state = RunState()
    state.bind("x", float("nan"))
    with pytest.raises(EvaluationError, match="non-finite"):
        ev("x == 1", state)
    state.bind("y", float("inf"))
    with pytest.raises(EvaluationError, match="non-finite"):
        ev("y", state)
    with pytest.raises(EvaluationError, match="non-finite"):
        resolve("y", state, now=0.0)
