"""Strictness: int-precise param typing and rejection of a binding with no single inferable
type. See design 2026-07-21 §3, §4.1, Engine A plan Task 4."""

from __future__ import annotations

from lab_devices.experiment.validate import validate
from tests.experiment_validate_helpers import diags, wf


def _valve_pos(value):
    return {"command": {"device": "valve_1", "verb": "set_position",
                        "params": {"position": value}}}


def test_int_param_given_a_float_expression_is_rejected() -> None:
    # valve.set_position.position is kind int; a number expression must not satisfy it.
    d = diags(wf([
        {"compute": {"into": "p", "value": "1.5"}},   # number
        _valve_pos("p"),
    ]))
    assert any(x.category == "type" for x in d)


def test_int_param_given_an_int_expression_passes() -> None:
    validate(wf([
        {"compute": {"into": "p", "value": "1 + 1"}},  # int
        _valve_pos("p"),
    ]))  # must not raise


def test_branch_conflicting_binding_types_is_rejected_at_use() -> None:
    # x is int on one arm, bool on the other -> join is 'unknown'; using it is a diagnostic.
    d = diags(wf([
        {"branch": {"if": "count(s) > 0",
                    "then": [{"compute": {"into": "x", "value": "1"}}],
                    "else": [{"compute": {"into": "x", "value": "count(s) > 0"}}]}},
        {"record": {"into": "s2", "value": "x"}},
    ], streams=["s", "s2"]))
    assert any(x.category == "type" and "x" in x.message for x in d)
