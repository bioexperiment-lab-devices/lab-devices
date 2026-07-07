import pytest

from lab_devices.experiment.errors import ExpressionError
from lab_devices.experiment.expr import (
    AllWindow,
    BinaryOp,
    BindingRef,
    Const,
    DurationWindow,
    SampleWindow,
    StatCall,
    UnaryOp,
    parse_expression,
    tokenize,
)


def test_tokenize_arithmetic():
    kinds = [(t.kind, t.text) for t in tokenize("2.0 * (a_1 - b)")]
    assert kinds == [
        ("NUMBER", "2.0"), ("OP", "*"), ("OP", "("), ("NAME", "a_1"),
        ("OP", "-"), ("NAME", "b"), ("OP", ")"), ("END", ""),
    ]


def test_tokenize_duration_and_comparison():
    kinds = [(t.kind, t.text) for t in tokenize("mean(OD, last=5min) >= x")]
    assert ("DURATION", "5min") in kinds
    assert ("OP", ">=") in kinds
    assert ("OP", "=") in kinds  # the 'last=' equals sign
    assert ("OP", ",") in kinds


def test_number_then_name_when_not_a_duration():
    kinds = [(t.kind, t.text) for t in tokenize("5msx")]
    assert kinds[0] == ("NUMBER", "5")
    assert kinds[1] == ("NAME", "msx")


def test_two_char_operators_lex_whole():
    ops = [t.text for t in tokenize("a <= b == c != d >= e") if t.kind == "OP"]
    assert ops == ["<=", "==", "!=", ">="]


def test_keywords_lex_as_plain_names():
    kinds = {(t.kind, t.text) for t in tokenize("true and not false or x")}
    assert ("NAME", "and") in kinds
    assert ("NAME", "not") in kinds
    assert ("NAME", "true") in kinds


def test_positions_recorded():
    assert [t.pos for t in tokenize("a + b")] == [0, 2, 4, 5]


def test_unexpected_character_raises():
    with pytest.raises(ExpressionError, match="unexpected character"):
        tokenize("a $ b")


def test_ast_node_equality():
    expr = BinaryOp("-", BindingRef("target_OD"), StatCall("mean", "OD", SampleWindow(100)))
    assert expr == BinaryOp(
        "-", BindingRef("target_OD"), StatCall("mean", "OD", SampleWindow(100))
    )


def test_number_literals():
    assert parse_expression("42") == Const(42)
    assert parse_expression("2.5") == Const(2.5)


def test_bool_literals():
    assert parse_expression("true") == Const(True)
    assert parse_expression("false") == Const(False)


def test_binding_reference():
    assert parse_expression("target_OD") == BindingRef("target_OD")


def test_stat_fn_name_usable_as_binding():
    assert parse_expression("min") == BindingRef("min")


def test_arithmetic_precedence():
    assert parse_expression("1 + 2 * 3") == BinaryOp(
        "+", Const(1), BinaryOp("*", Const(2), Const(3))
    )


def test_parentheses_override_precedence():
    assert parse_expression("(1 + 2) * 3") == BinaryOp(
        "*", BinaryOp("+", Const(1), Const(2)), Const(3)
    )


def test_left_associativity():
    assert parse_expression("8 - 2 - 1") == BinaryOp(
        "-", BinaryOp("-", Const(8), Const(2)), Const(1)
    )


def test_unary_minus():
    assert parse_expression("-x") == UnaryOp("-", BindingRef("x"))
    assert parse_expression("2 * -3") == BinaryOp("*", Const(2), UnaryOp("-", Const(3)))


def test_stat_call_default_window():
    assert parse_expression("count(OD)") == StatCall("count", "OD", AllWindow())


def test_stat_call_sample_window():
    assert parse_expression("mean(OD, last=100)") == StatCall("mean", "OD", SampleWindow(100))


def test_stat_call_duration_window():
    assert parse_expression("mean(OD, last=5min)") == StatCall(
        "mean", "OD", DurationWindow(300.0)
    )


def test_design_feedback_expression():
    assert parse_expression("2.0 * (target_OD - mean(OD, last=100))") == BinaryOp(
        "*",
        Const(2.0),
        BinaryOp("-", BindingRef("target_OD"), StatCall("mean", "OD", SampleWindow(100))),
    )


def test_design_until_condition():
    assert parse_expression("mean(OD, last=5min) >= target_OD") == BinaryOp(
        ">=", StatCall("mean", "OD", DurationWindow(300.0)), BindingRef("target_OD")
    )


def test_boolean_precedence_or_over_and():
    assert parse_expression("a and b or c") == BinaryOp(
        "or", BinaryOp("and", BindingRef("a"), BindingRef("b")), BindingRef("c")
    )


def test_not_binds_looser_than_comparison():
    assert parse_expression("not count(OD) > 0") == UnaryOp(
        "not", BinaryOp(">", StatCall("count", "OD", AllWindow()), Const(0))
    )


def test_comparison_of_arithmetic():
    assert parse_expression("a + 1 < b * 2") == BinaryOp(
        "<",
        BinaryOp("+", BindingRef("a"), Const(1)),
        BinaryOp("*", BindingRef("b"), Const(2)),
    )


@pytest.mark.parametrize("bad,fragment", [
    ("", "empty expression"),
    ("   ", "empty expression"),
    ("2 +", "expected a literal"),
    ("2 + * 3", "expected a literal"),
    ("(2", "expected"),
    ("2 2", "trailing input"),
    ("foo(OD)", "unknown function"),
    ("mean()", "stream name"),
    ("mean(OD, first=3)", "window must be"),
    ("mean(OD, last=2.5)", "must be an integer"),
    ("mean(OD, last=0)", "must be positive"),
    ("mean(OD, last=5 min)", "expected"),
    ("a < b < c", "cannot be chained"),
    ("5min + 3", "stat window"),
    ("2 + and", "unexpected keyword"),
])
def test_parse_errors(bad, fragment):
    with pytest.raises(ExpressionError, match=fragment):
        parse_expression(bad)
