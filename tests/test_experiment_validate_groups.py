from lab_devices.experiment.validate import validate
from tests.experiment_validate_helpers import diags, wf

DISPENSE = {"command": {"device": "pump_1", "verb": "dispense", "params": {"volume_ml": 1.0}}}


def test_unknown_group_ref():
    d = diags(wf([{"group_ref": {"name": "nope"}}]))
    assert any(
        x.category == "group" and "unknown group 'nope'" in x.message and x.path == "blocks[0]"
        for x in d
    )


def test_self_recursive_group():
    d = diags(wf(
        [{"group_ref": {"name": "a"}}],
        groups={"a": {"body": [{"group_ref": {"name": "a"}}]}},
    ))
    assert any(x.category == "group" and "recursive" in x.message for x in d)


def test_mutually_recursive_groups():
    groups = {
        "a": {"body": [{"group_ref": {"name": "b"}}]},
        "b": {"body": [{"group_ref": {"name": "a"}}]},
    }
    d = diags(wf([{"group_ref": {"name": "a"}}], groups=groups))
    assert any(x.category == "group" and "recursive" in x.message for x in d)


def test_acyclic_groups_pass():
    groups = {
        "leaf": {"body": [DISPENSE]},
        "mid": {"body": [{"group_ref": {"name": "leaf"}}]},
    }
    w = wf([{"group_ref": {"name": "mid"}}, {"group_ref": {"name": "leaf"}}], groups=groups)
    assert validate(w) is None


def test_diamond_is_not_recursion():
    groups = {
        "shared": {"body": [DISPENSE]},
        "a": {"body": [{"group_ref": {"name": "shared"}}]},
        "b": {"body": [{"group_ref": {"name": "shared"}}]},
    }
    w = wf(
        [{"group_ref": {"name": "a"}}, {"group_ref": {"name": "b"}}],
        groups=groups,
    )
    assert validate(w) is None


def test_group_ref_found_in_nested_containers():
    blocks = [{"serial": {"children": [
        {"parallel": {"children": [
            {"loop": {"count": 2, "body": [{"group_ref": {"name": "ghost"}}]}},
        ]}},
    ]}}]
    d = diags(wf(blocks))
    assert any(x.path == "blocks[0].children[0].children[0].body[0]" for x in d)


def test_unknown_ref_inside_group_body():
    d = diags(wf([], groups={"a": {"body": [{"group_ref": {"name": "ghost"}}]}}))
    assert any(x.path == "groups['a'].body[0]" and x.category == "group" for x in d)


def test_branch_else_paths():
    blocks = [{"branch": {
        "if": "1 < 2",
        "then": [DISPENSE],
        "else": [{"group_ref": {"name": "ghost"}}],
    }}]
    d = diags(wf(blocks))
    assert any(x.path == "blocks[0].else[0]" for x in d)
