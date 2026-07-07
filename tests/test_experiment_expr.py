import pytest

from lab_devices.experiment.errors import ExpressionError
from lab_devices.experiment.expr import (
    BinaryOp,
    BindingRef,
    SampleWindow,
    StatCall,
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
