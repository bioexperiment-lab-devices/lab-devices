from lab_devices.experiment.analyze import ExprRefs, TypeReport, infer_type, references
from lab_devices.experiment.expr import parse_expression


def refs(text):
    return references(parse_expression(text))


def report(text, bindings=None):
    return infer_type(parse_expression(text), bindings or {})


def test_references_bindings_and_streams():
    r = refs("2.0 * (target - mean(OD, last=100)) + last(temp)")
    assert r.bindings == frozenset({"target"})
    assert r.streams_windowed == frozenset({"OD", "temp"})
    assert r.streams_counted == frozenset()


def test_references_count_separated():
    r = refs("count(OD) > 0 and mean(OD) > x or count(pressure) == 0")
    assert r.bindings == frozenset({"x"})
    assert r.streams_windowed == frozenset({"OD"})
    assert r.streams_counted == frozenset({"OD", "pressure"})


def test_references_literals_only():
    assert refs("1 + 2 < 4") == ExprRefs(frozenset(), frozenset(), frozenset())


def test_references_unary_and_nesting():
    r = refs("not (a > -b)")
    assert r.bindings == frozenset({"a", "b"})


def test_infer_const_and_stat_types():
    assert report("1 + 2.5").type == "number"
    assert report("true").type == "boolean"
    assert report("1 < 2").type == "boolean"
    assert report("not (1 < 2)").type == "boolean"
    assert report("-(3 * 2)").type == "number"
    assert report("mean(OD)").type == "number"
    assert report("count(OD) >= 3").type == "boolean"


def test_infer_binding_types():
    assert report("x + 1", {"x": "number"}) == TypeReport("number", ())
    assert report("flag and true", {"flag": "boolean"}) == TypeReport("boolean", ())
    assert report("x", {}).type == "unknown"
    assert report("x + 1").type == "number"  # unknown operand: no false positive


def test_string_binding_is_a_problem():
    rep = report("mode_sel + 1", {"mode_sel": "string"})
    assert any("string" in p for p in rep.problems)


def test_boolean_number_mixes_are_problems():
    assert report("true + 1").problems
    assert report("1 and 2").problems
    assert report("not 3").problems
    assert report("-true").problems
    assert report("true > false").problems
    assert report("(1 < 2) == 3").problems


def test_equality_same_kind_ok():
    assert report("(1 < 2) == (3 < 4)") == TypeReport("boolean", ())
    assert report("1 == 2") == TypeReport("boolean", ())


def test_unknown_propagates_without_problems():
    rep = report("x + 1 > 0 and y", {})
    assert rep.type == "boolean"
    assert rep.problems == ()


def test_multiple_problems_collected():
    rep = report("(true + 1) * (not 2)")
    assert len(rep.problems) >= 2
