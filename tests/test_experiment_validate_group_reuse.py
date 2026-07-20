"""A plain (param-less, local-less) group is lazily inlined: its body is expanded once,
eagerly, no matter how many group_refs later name it (design 2026-07-20 §2.2, §6). If that
frozen body reaches a locals-bearing group_ref, referencing the plain group more than once
would silently replay one resolved instance twice -- Task 5/6's expand.py never noticed
because the duplicate-instance check only ever runs once, during that single eager pass.
"""

from lab_devices.experiment.validate import validate
from tests.experiment_validate_helpers import diags, wf

DISPENSE = {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}}

_LOCALS_BEARING_SVC = {
    "locals": {"c": {"kind": "binding", "init": "0"}},
    "body": [{"compute": {"into": "{c}", "value": "{c} + 1"}}],
}


def _wash_groups():
    return {
        "wash": {"body": [{"group_ref": {"name": "svc", "as": "t1", "args": {}}}]},
        "svc": _LOCALS_BEARING_SVC,
    }


def test_plain_group_referenced_twice_with_a_nested_locals_ref_is_rejected():
    d = diags(wf(
        [{"group_ref": {"name": "wash"}}, {"group_ref": {"name": "wash"}}],
        groups=_wash_groups(),
    ))
    assert any(
        x.category == "group" and "plain group 'wash' is referenced 2 times" in x.message
        for x in d
    )


def test_plain_group_referenced_once_with_a_nested_locals_ref_is_clean():
    w = wf([{"group_ref": {"name": "wash"}}], groups=_wash_groups())
    assert validate(w) is None


def test_plain_group_reused_without_locals_is_still_clean():
    # No locals anywhere reachable from "wash" -- the existing, legitimate lazy-inline
    # reuse pattern (design 2026-07-20 §2.2); test_diamond_is_not_recursion already
    # covers the diamond shape of this for a plain group with no locals at all.
    groups = {"wash": {"body": [DISPENSE]}}
    w = wf(
        [{"group_ref": {"name": "wash"}}, {"group_ref": {"name": "wash"}}],
        groups=groups,
    )
    assert validate(w) is None


def test_plain_group_reused_via_a_for_each_is_rejected():
    # for_each's row count is known statically (authored data), so a single group_ref
    # textually written once, but sitting inside a 2-row for_each, is weighted as 2.
    d = diags(wf(
        [{"for_each": {"vars": [{"name": "i", "kind": "int"}],
                       "in": [{"i": 1}, {"i": 2}],
                       "body": [{"group_ref": {"name": "wash"}}]}}],
        groups=_wash_groups(),
    ))
    assert any(
        x.category == "group" and "plain group 'wash' is referenced 2 times" in x.message
        for x in d
    )


def test_plain_group_reused_via_another_plain_group_is_rejected():
    # Transitive: "outer" is plain and lazily inlines "wash" (also plain), which nests
    # the locals-bearing ref. Referencing "outer" twice aliases just the same, since
    # "wash"'s own body -- and the instance it resolves -- is frozen once regardless.
    groups = {"outer": {"body": [{"group_ref": {"name": "wash"}}]}, **_wash_groups()}
    d = diags(wf(
        [{"group_ref": {"name": "outer"}}, {"group_ref": {"name": "outer"}}],
        groups=groups,
    ))
    assert any(
        x.category == "group" and "plain group 'outer' is referenced 2 times" in x.message
        for x in d
    )


def test_plain_group_referenced_twice_through_a_parametrized_intermediate_is_rejected():
    # wash(plain) -> group_ref mid{n:1}; mid(params n) -> group_ref svc as t1; svc(locals c).
    # Reachability must traverse the PARAMETRIZED "mid" hop, not just plain intermediates:
    # mid's args are fixed as authored inside wash's single frozen expansion, so the hazard
    # is identical to a direct plain -> locals-bearing chain.
    groups = {
        "wash": {"body": [{"group_ref": {"name": "mid", "args": {"n": 1}}}]},
        "mid": {
            "params": [{"name": "n", "kind": "int"}],
            "body": [{"group_ref": {"name": "svc", "as": "t1", "args": {}}}],
        },
        "svc": _LOCALS_BEARING_SVC,
    }
    d = diags(wf(
        [{"group_ref": {"name": "wash"}}, {"group_ref": {"name": "wash"}}],
        groups=groups,
    ))
    assert any(
        x.category == "group" and "plain group 'wash' is referenced 2 times" in x.message
        for x in d
    )


def test_plain_group_ref_inside_an_uncalled_group_does_not_inflate_the_count():
    # "unused" is never referenced from `blocks` or from any group reachable from `blocks`,
    # so its own group_ref to "wash" must not count toward wash's reuse total.
    groups = {**_wash_groups(), "unused": {"body": [{"group_ref": {"name": "wash"}}]}}
    w = wf([{"group_ref": {"name": "wash"}}], groups=groups)
    assert validate(w) is None


def test_a_non_plain_group_may_be_referenced_many_times():
    # A group with params re-substitutes fresh at every call site, so the existing live
    # duplicate-`as` check in expand._open_locals is what guards it, not this check.
    groups = {"svc": {
        "params": [{"name": "tube", "kind": "int"}],
        "locals": {"c": {"kind": "binding", "init": "0"}},
        "body": [{"compute": {"into": "{c}", "value": "{c} + {tube}"}}],
    }}
    w = wf(
        [{"group_ref": {"name": "svc", "as": "t1", "args": {"tube": 1}}},
         {"group_ref": {"name": "svc", "as": "t2", "args": {"tube": 2}}}],
        groups=groups,
    )
    assert validate(w) is None
