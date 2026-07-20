import pytest

from lab_devices.experiment import blocks as B
from lab_devices.experiment.errors import ValidationError
from lab_devices.experiment.serialize import workflow_from_dict
from lab_devices.experiment.validate import validate
from lab_devices.experiment.workflow import Defaults, Workflow


def _validate(doc):
    validate(workflow_from_dict(doc))


def _messages(exc):
    return [d.message for d in exc.value.diagnostics]


_ROLES_DOC = {"pump_1": {"type": "pump"}, "densitometer_1": {"type": "densitometer"}}


def test_retry_on_a_wait_block_is_rejected():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 2,
            "blocks": [{"wait": {"duration": "1s"}, "retry": {"attempts": 3}}],
        })
    assert any("only valid on command and measure" in m for m in _messages(exc))


def test_retry_on_dispense_without_allow_repeat_is_rejected():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 2,
            "roles": _ROLES_DOC,
            "blocks": [{
                "command": {"device": "pump_1", "verb": "dispense",
                            "params": {"volume_ml": 0.5}},
                "retry": {"attempts": 3},
            }],
        })
    assert any("not idempotent" in m for m in _messages(exc))


def test_retry_on_dispense_with_allow_repeat_is_accepted():
    _validate({
        "schema_version": 2,
        "roles": _ROLES_DOC,
        "blocks": [{
            "command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 0.5}},
            "retry": {"attempts": 3, "allow_repeat": True},
        }],
    })


def test_retry_on_a_measure_needs_no_opt_in():
    _validate({
        "schema_version": 2,
        "roles": _ROLES_DOC,
        "streams": {"od_1": {}},
        "blocks": [{
            "measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
            "retry": {"attempts": 3, "backoff": "2s"},
        }],
    })


def test_defaults_retry_may_not_set_allow_repeat():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 2,
            "defaults": {"retry": {"attempts": 2, "allow_repeat": True}},
            "blocks": [{"wait": {"duration": "1s"}}],
        })
    assert any("blanket policy" in m for m in _messages(exc))


def test_defaults_retry_over_a_non_idempotent_verb_still_validates():
    """The validator ACCEPTS this: a workflow-scoped default cannot be checked against a
    per-block verb, so it diagnoses nothing here. That a blanket default never actually
    retries `dispense` is enforced at execution time, by _effective_retry consulting
    Trait.retry_safe -- the guarantee is held by
    tests/test_experiment_retry.py::test_workflow_defaults_never_retry_a_non_idempotent_verb,
    NOT by this test. Do not read this as a validator-enforced property.
    """
    _validate({
        "schema_version": 2,
        "roles": _ROLES_DOC,
        "defaults": {"retry": {"attempts": 3}},
        "blocks": [{
            "command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 0.5}}
        }],
    })


def test_retry_attempts_below_one_on_a_programmatic_ast_is_rejected():
    """The loader enforces attempts >= 1; the Python API does not, and ExperimentRun.__init__
    calls validate(), not the loader. attempts=0 would dispatch the block zero times and land
    in the executor's 'unreachable' branch."""
    w = Workflow(
        schema_version=1,
        blocks=[B.Command(device="pump_1", verb="stop", retry=B.Retry(attempts=0))],
    )
    with pytest.raises(ValidationError) as exc:
        validate(w)
    assert any("retry.attempts must be >= 1" in m for m in _messages(exc))


def test_defaults_retry_attempts_below_one_on_a_programmatic_ast_is_rejected():
    w = Workflow(
        schema_version=1,
        blocks=[B.Wait(duration="1s")],
        defaults=Defaults(retry=B.Retry(attempts=0)),
    )
    with pytest.raises(ValidationError) as exc:
        validate(w)
    assert any("retry.attempts must be >= 1" in m for m in _messages(exc))


def test_on_error_continue_is_accepted_on_every_container():
    _validate({
        "schema_version": 2,
        "groups": {"g": {"body": [{"wait": {"duration": "1s"}}]}},
        "blocks": [
            {"serial": {"children": [{"wait": {"duration": "1s"}}]}, "on_error": "continue"},
            {"parallel": {"children": [{"wait": {"duration": "1s"}}]}, "on_error": "continue"},
            {"wait": {"duration": "1s"}, "on_error": "continue"},
            {
                "loop": {"count": 1, "body": [{"wait": {"duration": "1s"}}]},
                "on_error": "continue",
            },
            {
                "branch": {"if": "true", "then": [{"wait": {"duration": "1s"}}]},
                "on_error": "continue",
            },
            {"group_ref": {"name": "g"}, "on_error": "continue"},
        ],
    })


def test_bad_on_error_on_a_programmatic_ast_is_rejected():
    w = Workflow(schema_version=1, blocks=[B.Wait(duration="1s", on_error="retry")])
    with pytest.raises(ValidationError) as exc:
        validate(w)
    assert any("on_error must be one of" in m for m in _messages(exc))


_TOLERANT_MEASURE = {
    "measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"},
    "retry": {"attempts": 3, "backoff": "2s"},
    "on_error": "continue",
}


def test_tolerated_measure_then_unguarded_windowed_read_is_rejected():
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 2,
            "roles": _ROLES_DOC,
            "streams": {"od_1": {}},
            "blocks": [
                _TOLERANT_MEASURE,
                {"branch": {"if": "mean(od_1, last=3) > 0.4",
                            "then": [{"wait": {"duration": "1s"}}]}},
            ],
        })
    assert any("no preceding measure" in d.message for d in exc.value.diagnostics)


def test_tolerated_measure_guarded_by_a_count_branch_validates():
    _validate({
        "schema_version": 2,
        "roles": _ROLES_DOC,
        "streams": {"od_1": {}},
        "blocks": [
            _TOLERANT_MEASURE,
            {"branch": {
                "if": "count(od_1) > 0",
                "then": [{"branch": {"if": "mean(od_1, last=3) > 0.4",
                                     "then": [{"wait": {"duration": "1s"}}]}}],
            }},
        ],
    })


def test_tolerated_measure_guarded_by_a_short_circuit_and_validates():
    """evaluate.py:85 documents this idiom; the analyzer now recognises it."""
    _validate({
        "schema_version": 2,
        "roles": _ROLES_DOC,
        "streams": {"od_1": {}},
        "blocks": [
            _TOLERANT_MEASURE,
            {"branch": {"if": "count(od_1) > 0 and mean(od_1, last=3) > 0.4",
                        "then": [{"wait": {"duration": "1s"}}]}},
        ],
    })


def test_an_untolerated_measure_still_needs_no_guard():
    """Regression: the existing definitely-written proof must not weaken."""
    _validate({
        "schema_version": 2,
        "roles": _ROLES_DOC,
        "streams": {"od_1": {}},
        "blocks": [
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"}},
            {"branch": {"if": "mean(od_1, last=3) > 0.4",
                        "then": [{"wait": {"duration": "1s"}}]}},
        ],
    })


def _guarded(condition, blocks=None):
    """A tolerated measure, then `condition` as a branch guard."""
    return {
        "schema_version": 2,
        "roles": _ROLES_DOC,
        "streams": {"od_1": {}},
        "blocks": [
            _TOLERANT_MEASURE,
            {"branch": {"if": condition,
                        "then": blocks or [{"wait": {"duration": "1s"}}]}},
        ],
    }


def test_a_bare_count_guard_does_not_discharge_a_duration_window_read():
    """The soundness hole. `_window_values` slices a duration window by timestamp cutoff, so
    a stream can be non-empty — count(od_1) > 0 true — while its last 5 minutes are empty.
    A sustained sensor outage is exactly what on_error: continue exists to survive AND what
    ages the newest sample out of the window, so this must not validate."""
    with pytest.raises(ValidationError) as exc:
        _validate(_guarded("count(od_1) > 0 and mean(od_1, last=5min) > 0.4"))
    assert any("duration window" in m for m in _messages(exc))


def test_a_duration_guard_matching_the_read_validates():
    _validate(_guarded("count(od_1, last=5min) > 0 and mean(od_1, last=5min) > 0.4"))


def test_a_guard_window_wider_than_the_read_is_rejected():
    """A sample within the last 10 minutes says nothing about the last 5."""
    with pytest.raises(ValidationError) as exc:
        _validate(_guarded("count(od_1, last=10min) > 0 and mean(od_1, last=5min) > 0.4"))
    assert any("count(od_1, last=300s) > 0" in m for m in _messages(exc))


def test_a_guard_window_narrower_than_the_read_is_accepted():
    """A sample within the last 5 minutes is necessarily within the last 10."""
    _validate(_guarded("count(od_1, last=5min) > 0 and mean(od_1, last=10min) > 0.4"))


def test_a_bare_count_guard_still_discharges_sample_and_whole_stream_reads():
    """The morbidostat's actual idiom must keep working: `samples[-n:]` of a non-empty
    stream is never empty, so count(od_1) > 0 discharges every non-duration read."""
    _validate(_guarded(
        "count(od_1) > 0 and mean(od_1, last=3) > 0.4 and mean(od_1) > last(od_1) - 1"
    ))


def test_a_guard_to_the_right_of_an_and_does_not_protect_reads_to_its_left():
    """The evaluator short-circuits left-to-right (evaluate.py:85): `mean` is evaluated
    before `count(od_1) > 0` ever runs, so a guard to the right of the read is no guard at
    all — if every attempt of the tolerated measure fails, `mean` raises on an empty
    window regardless of what the untaken right operand would have proved."""
    with pytest.raises(ValidationError) as exc:
        _validate(_guarded("mean(od_1, last=3) > 0.4 and count(od_1) > 0"))
    assert any("no preceding measure" in d.message for d in exc.value.diagnostics)


def test_the_branch_then_form_matches_the_and_form():
    """Same guards, same reads, seeded through branch.then instead of an `and` chain."""
    body = [{"branch": {"if": "mean(od_1, last=3) > 0.4",
                        "then": [{"wait": {"duration": "1s"}}]}}]
    _validate(_guarded("count(od_1) > 0", body))  # accepted, exactly as in the `and` form
    duration_body = [{"branch": {"if": "mean(od_1, last=5min) > 0.4",
                                 "then": [{"wait": {"duration": "1s"}}]}}]
    with pytest.raises(ValidationError) as exc:  # rejected, exactly as in the `and` form
        _validate(_guarded("count(od_1) > 0", duration_body))
    assert any("duration window" in m for m in _messages(exc))


def test_a_duration_guard_does_not_cross_into_the_branch_body():
    """A duration proof holds for the expression that establishes it (one `now`), but not
    for the body it guards: `now` advances as soon as the body runs, so a duration-windowed
    read anywhere inside `then` needs its own guard — whether or not a `wait` sits before it.
    (A `wait` is not what breaks the proof; merely running the body does.)"""
    with_wait = [
        {"wait": {"duration": "10min"}},
        {"branch": {"if": "mean(od_1, last=5min) > 0.4",
                    "then": [{"wait": {"duration": "1s"}}]}},
    ]
    without_wait = [
        {"branch": {"if": "mean(od_1, last=5min) > 0.4",
                    "then": [{"wait": {"duration": "1s"}}]}},
    ]
    for body in (with_wait, without_wait):
        with pytest.raises(ValidationError) as exc:
            _validate(_guarded("count(od_1, last=5min) > 0", body))
        assert any("duration window" in m for m in _messages(exc))


def test_a_branch_guard_does_not_seed_the_else_arm():
    """The guard proves od_1 non-empty on the `then` side, where `count(od_1) > 0` is TRUE.
    On the `else` side it is FALSE — od_1 may be empty there — so seeding else_state with
    the same proof would be unsound. A windowed read nested in the else arm must still be
    rejected for want of a guard."""
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 2,
            "roles": _ROLES_DOC,
            "streams": {"od_1": {}},
            "blocks": [
                _TOLERANT_MEASURE,
                {"branch": {
                    "if": "count(od_1) > 0",
                    "then": [{"wait": {"duration": "1s"}}],
                    "else": [{"branch": {"if": "mean(od_1, last=3) > 0.4",
                                         "then": [{"wait": {"duration": "1s"}}]}}],
                }},
            ],
        })
    assert any("no preceding measure" in d.message for d in exc.value.diagnostics)


def test_a_branch_guard_does_not_leak_past_the_branch():
    """_merge intersects `nonempty` back out at the branch's exit (the `then` side has the
    proof, the untaken `else` side does not), so a read after the branch closes must not
    inherit the `then` arm's proof."""
    with pytest.raises(ValidationError) as exc:
        _validate({
            "schema_version": 2,
            "roles": _ROLES_DOC,
            "streams": {"od_1": {}},
            "blocks": [
                _TOLERANT_MEASURE,
                {"branch": {"if": "count(od_1) > 0",
                            "then": [{"wait": {"duration": "1s"}}]}},
                {"branch": {"if": "mean(od_1, last=3) > 0.4",
                            "then": [{"wait": {"duration": "1s"}}]}},
            ],
        })
    assert any("no preceding measure" in d.message for d in exc.value.diagnostics)


def test_an_untolerated_measure_still_allows_a_duration_window_read():
    """Pre-existing gap, deliberately preserved: a definite write discharges *any* window,
    duration included, even though it does not strictly prove one non-empty. Rejecting it
    is a separate strictness change (design 2026-07-14 §5.2 note)."""
    _validate({
        "schema_version": 2,
        "roles": _ROLES_DOC,
        "streams": {"od_1": {}},
        "blocks": [
            {"measure": {"device": "densitometer_1", "verb": "measure", "into": "od_1"}},
            {"wait": {"duration": "10min"}},
            {"branch": {"if": "mean(od_1, last=5min) > 0.4",
                        "then": [{"wait": {"duration": "1s"}}]}},
        ],
    })
