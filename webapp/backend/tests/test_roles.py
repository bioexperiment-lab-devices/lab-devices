"""Role checks + placeholder/real substitution (design §4.2-4.3)."""

from typing import Any

from experiment_studio import roles
from experiment_studio.roles import placeholder_ids, role_diagnostics, substitute
from lab_devices.experiment import serialize


def test_placeholder_ids_count_per_type_in_insertion_order() -> None:
    roles = {"feed": "pump", "od": "densitometer", "waste": "pump"}
    assert placeholder_ids(roles) == {
        "feed": "pump_0",
        "od": "densitometer_0",
        "waste": "pump_1",
    }


def test_role_diagnostics_name_shape_and_unknown_type() -> None:
    diags = role_diagnostics({"Feed_Pump": "pump", "mixer": "stirrer"}, {"pump"})
    assert diags == [
        {
            "category": "roles",
            "path": "roles['Feed_Pump']",
            "message": "role name 'Feed_Pump' must match [a-z][a-z0-9_]*",
        },
        {
            "category": "roles",
            "path": "roles['mixer']",
            "message": "unknown device type 'stirrer'",
        },
    ]


def test_role_diagnostics_clean() -> None:
    assert role_diagnostics({"feed_pump": "pump"}, {"pump"}) == []


def _workflow() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "streams": {"od": {"units": "AU"}},
        "groups": {
            "wash": {"body": [{"command": {"device": "feed", "verb": "stop"}}]},
        },
        "blocks": [
            {"serial": {"children": [
                {"command": {"device": "feed", "verb": "dispense",
                             "params": {"volume_ml": 5}}},
                {"loop": {"count": 2, "body": [
                    {"measure": {"device": "od", "verb": "measure", "into": "od"}},
                ]}},
                {"branch": {"if": "x > 1", "then": [
                    {"command": {"device": "feed", "verb": "stop"}},
                ], "else": [
                    {"parallel": {"children": [
                        {"command": {"device": "feed", "verb": "stop"}},
                        {"wait": {"duration": "5s"}},
                    ]}},
                ]}},
            ]}},
        ],
    }


def test_substitute_walks_every_container_kind() -> None:
    mapping = {"feed": "pump_0", "od": "densitometer_0"}
    out, diags = substitute(_workflow(), mapping)
    assert diags == []
    serial = out["blocks"][0]["serial"]["children"]
    assert serial[0]["command"]["device"] == "pump_0"
    assert serial[1]["loop"]["body"][0]["measure"]["device"] == "densitometer_0"
    assert serial[2]["branch"]["then"][0]["command"]["device"] == "pump_0"
    par = serial[2]["branch"]["else"][0]["parallel"]["children"]
    assert par[0]["command"]["device"] == "pump_0"
    assert out["groups"]["wash"]["body"][0]["command"]["device"] == "pump_0"


def test_substitute_does_not_mutate_input() -> None:
    original = _workflow()
    substitute(original, {"feed": "pump_0", "od": "densitometer_0"})
    assert original["blocks"][0]["serial"]["children"][0]["command"]["device"] == "feed"


def test_substitute_reports_unknown_role_at_block_path() -> None:
    wf = {
        "schema_version": 1,
        "blocks": [
            {"serial": {"children": [
                {"wait": {"duration": "1s"}},
                {"command": {"device": "ghost", "verb": "stop"}},
            ]}},
        ],
        "groups": {"wash": {"body": [{"measure": {"device": "phantom", "into": "od"}}]}},
    }
    out, diags = substitute(wf, {})
    assert diags == [
        {
            "category": "roles",
            "path": "blocks[0].children[1]",
            "message": "block references unknown role 'ghost'",
        },
        {
            "category": "roles",
            "path": "groups['wash'].body[0]",
            "message": "block references unknown role 'phantom'",
        },
    ]
    assert out["blocks"][0]["serial"]["children"][1]["command"]["device"] == "ghost"


def test_substitute_skips_malformed_nodes_without_crashing() -> None:
    wf = {
        "schema_version": 1,
        "blocks": [
            "not-a-dict",
            {"command": {"device": "feed", "verb": "stop"}, "serial": {"children": []}},
            {"command": "not-an-object"},
            {"command": {"device": 42, "verb": "stop"}},
        ],
    }
    out, diags = substitute(wf, {"feed": "pump_0"})
    assert diags == []  # malformed shapes are the engine loader's job to report
    assert out["blocks"][0] == "not-a-dict"
    assert out["blocks"][3]["command"]["device"] == 42


def test_substitute_handles_blocks_with_retry_and_on_error() -> None:
    workflow = {
        "schema_version": 1,
        "streams": {"od_1": {}},
        "blocks": [{
            "measure": {"device": "od_meter", "verb": "measure", "into": "od_1"},
            "retry": {"attempts": 3, "backoff": "2s"},
            "on_error": "continue",
        }],
    }
    out, diags = roles.substitute(workflow, {"od_meter": "densitometer_1"})
    assert diags == []
    assert out["blocks"][0]["measure"]["device"] == "densitometer_1"
    assert out["blocks"][0]["retry"] == {"attempts": 3, "backoff": "2s"}
    assert out["blocks"][0]["on_error"] == "continue"


def test_walker_grammar_matches_engine_serializer() -> None:
    assert roles._BLOCK_KEYS == serialize._BLOCK_KEYS
    covered = (
        set(roles._DEVICE_BLOCKS) | set(roles._CHILD_LISTS) | set(roles._LEAF_BLOCKS)
    )
    assert covered == set(serialize._BUILDERS)
    assert set(roles._DEVICE_BLOCKS) == {"command", "measure"}
    assert roles._CHILD_LISTS == {
        "serial": ("children",),
        "parallel": ("children",),
        "loop": ("body",),
        "branch": ("then", "else"),
    }
