"""Compute bindings are typed by inference, so a mismatch through a computed binding is a
load-time diagnostic instead of a runtime EvaluationError. See design 2026-07-21 §4.1,
Engine A plan Task 3."""

from __future__ import annotations

from lab_devices.experiment.validate import validate
from tests.experiment_validate_helpers import diags, wf


def test_computed_number_binding_used_as_guard_is_rejected() -> None:
    # x is inferred int (from "1"); a guard wants a bool.
    d = diags(wf([
        {"compute": {"into": "x", "value": "1"}},
        {"branch": {"if": "x", "then": []}},
    ]))
    assert any(x.category == "type" for x in d)


def test_computed_boolean_binding_used_in_arithmetic_is_rejected() -> None:
    # flag is inferred bool (from "count(s) > 0"); arithmetic on a bool is a type error.
    d = diags(wf([
        {"compute": {"into": "flag", "value": "count(s) > 0"}},
        {"record": {"into": "s2", "value": "flag + 1"}},
    ], streams=["s", "s2"]))
    assert any(x.category == "type" and "flag" in x.message for x in d)


def test_consistent_computed_binding_use_passes() -> None:
    # flag is bool and is used as a bool guard: no diagnostic.
    validate(wf([
        {"compute": {"into": "flag", "value": "count(s) > 0"}},
        {"branch": {"if": "flag", "then": []}},
    ], streams=["s"]))  # must not raise
