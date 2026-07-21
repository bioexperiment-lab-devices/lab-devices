"""The scalar type lattice: `int <: number`, invariance of bool/string, unknown leniency.
See design 2026-07-21 §3.1 and Engine A plan Task 1."""

from __future__ import annotations

from lab_devices.experiment.analyze import assignable, infer_type
from lab_devices.experiment.expr import parse_expression


def _t(text: str, binds: dict[str, str] | None = None):
    return infer_type(parse_expression(text), binds or {})


def test_assignable_reflexive() -> None:
    for t in ("int", "number", "bool", "string"):
        assert assignable(t, t)


def test_int_is_a_number_but_not_the_reverse() -> None:
    assert assignable("int", "number")
    assert not assignable("number", "int")


def test_bool_and_string_are_invariant() -> None:
    assert not assignable("bool", "number")
    assert not assignable("string", "number")
    assert not assignable("number", "bool")
    assert not assignable("string", "bool")


def test_unknown_is_leniently_assignable_either_way() -> None:
    # `unknown` is the transient inference state; operand-level checks stay lenient,
    # strictness is enforced at slot level (design §3, plan Task 4).
    assert assignable("unknown", "number")
    assert assignable("number", "unknown")


# --- infer_type node rules (design §5, plan Task 2) ---


def test_integer_literal_and_count_are_int() -> None:
    assert _t("5").type == "int"
    assert _t("count(s)").type == "int"
    assert _t("5.0").type == "number"


def test_int_arithmetic_stays_int_but_division_and_float_widen() -> None:
    assert _t("2 + 3").type == "int"
    assert _t("2 * 3").type == "int"
    assert _t("2 / 3").type == "number"  # real division always widens
    assert _t("2 + 3.0").type == "number"
    assert _t("-2").type == "int"  # unary minus preserves int


def test_stat_over_stream_is_number() -> None:
    assert _t("mean(s)").type == "number"
    assert _t("last(s)").type == "number"


def test_string_binding_flows_as_string_without_a_problem() -> None:
    r = _t("mode", {"mode": "string"})
    assert r.type == "string"
    assert r.problems == ()


def test_string_equality_is_allowed() -> None:
    r = _t("mode == mode", {"mode": "string"})
    assert r.type == "bool"
    assert r.problems == ()


def test_string_in_arithmetic_is_a_problem() -> None:
    r = _t("mode + 1", {"mode": "string"})
    assert r.problems  # string is not a number


def test_comparing_string_with_number_is_a_problem() -> None:
    r = _t("mode == 1", {"mode": "string"})
    assert r.problems


def test_numeric_guard_is_still_a_number_not_a_bool() -> None:
    # count(s) is int; used directly as a boolean it is caught at the slot (Task 4),
    # but the *inferred* type here is int, not bool.
    assert _t("count(s)").type == "int"
