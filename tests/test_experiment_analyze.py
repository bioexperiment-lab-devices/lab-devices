from lab_devices.experiment.analyze import (
    ExprRefs,
    TypeReport,
    infer_type,
    proof_covers,
    proven_nonempty,
    references,
)
from lab_devices.experiment.expr import (
    AllWindow,
    DurationWindow,
    SampleWindow,
    parse_expression,
)


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


def test_proven_nonempty_recognises_count_guards():
    assert proven_nonempty(parse_expression("count(od_1) > 0")) == {"od_1": AllWindow()}
    assert proven_nonempty(parse_expression("count(od_1) >= 1")) == {"od_1": AllWindow()}
    assert proven_nonempty(parse_expression("count(od_1) != 0")) == {"od_1": AllWindow()}
    assert proven_nonempty(parse_expression("0 < count(od_1)")) == {"od_1": AllWindow()}
    assert proven_nonempty(parse_expression("count(od_1) > 5")) == {"od_1": AllWindow()}


def test_proven_nonempty_rejects_non_guards():
    assert proven_nonempty(parse_expression("count(od_1) >= 0")) == {}
    assert proven_nonempty(parse_expression("count(od_1) < 3")) == {}
    assert proven_nonempty(parse_expression("mean(od_1, last=3) > 0.4")) == {}


def test_proven_nonempty_combines_over_and_or():
    both = proven_nonempty(parse_expression("count(od_1) > 0 and count(od_2) > 0"))
    assert both == {"od_1": AllWindow(), "od_2": AllWindow()}
    either = proven_nonempty(parse_expression("count(od_1) > 0 or count(od_2) > 0"))
    assert either == {}
    same = proven_nonempty(parse_expression("count(od_1) > 0 or count(od_1) > 3"))
    assert same == {"od_1": AllWindow()}


def test_proven_nonempty_carries_the_guards_window():
    """A sample-count guard proves exactly what a whole-stream guard does, so it normalises
    to AllWindow; a duration guard proves strictly more and keeps its window."""
    sample = proven_nonempty(parse_expression("count(od_1, last=3) > 0"))
    assert sample == {"od_1": AllWindow()}
    duration = proven_nonempty(parse_expression("count(od_1, last=5min) > 0"))
    assert duration == {"od_1": DurationWindow(300.0)}


def test_proven_nonempty_and_takes_the_strongest_proof_or_the_weakest():
    strongest = proven_nonempty(
        parse_expression("count(od_1, last=10min) > 0 and count(od_1, last=5min) > 0")
    )
    assert strongest == {"od_1": DurationWindow(300.0)}  # the narrower window proves more
    weakest = proven_nonempty(
        parse_expression("count(od_1, last=10min) > 0 or count(od_1, last=5min) > 0")
    )
    assert weakest == {"od_1": DurationWindow(600.0)}  # only the wider one is guaranteed
    degraded = proven_nonempty(
        parse_expression("count(od_1, last=5min) > 0 or count(od_1) > 0")
    )
    assert degraded == {"od_1": AllWindow()}  # the bare count is the weaker of the two


def test_proof_covers_is_window_aware():
    """`count(S) > 0` does NOT prove a duration window non-empty: `_window_values` slices a
    DurationWindow by timestamp cutoff, so a stale stream is non-empty with an empty window.
    A sample window is different — `samples[-n:]` of a non-empty stream is never empty."""
    assert proof_covers(AllWindow(), AllWindow())
    assert proof_covers(AllWindow(), SampleWindow(3))
    assert not proof_covers(AllWindow(), DurationWindow(300.0))
    # A duration proof implies the stream holds a sample, so it discharges the others too.
    assert proof_covers(DurationWindow(300.0), AllWindow())
    assert proof_covers(DurationWindow(300.0), SampleWindow(3))
    # Duration vs duration: the read's window must contain the guard's.
    assert proof_covers(DurationWindow(300.0), DurationWindow(300.0))
    assert proof_covers(DurationWindow(300.0), DurationWindow(600.0))
    assert not proof_covers(DurationWindow(600.0), DurationWindow(300.0))
