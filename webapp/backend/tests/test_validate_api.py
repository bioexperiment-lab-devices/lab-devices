"""POST /api/validate: doc-level checks + placeholder substitution + engine diagnostics
mapping (design §4.3), against the golden fixtures in webapp/fixtures/."""

import json
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


async def test_valid_doc_is_clean(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/validate", json=load_fixture("valid-od-growth.json"))
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "diagnostics": []}


async def test_valid_control_blocks_doc_is_clean(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/validate", json=load_fixture("valid-control-blocks.json"))
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "diagnostics": []}


async def test_doc_level_diagnostics(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/validate", json=load_fixture("invalid-roles.json"))
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": False,
        "diagnostics": [
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
            {
                "category": "roles",
                "path": "blocks[0]",
                "message": "block references unknown role 'ghost_pump'",
            },
        ],
    }


async def test_engine_diagnostics_pass_through_with_structural_paths(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post("/api/validate", json=load_fixture("invalid-workflow.json"))
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": False,
        "diagnostics": [
            {
                "category": "params",
                "path": "blocks[0].children[0]",
                "message": "missing required param 'volume_ml' for verb 'dispense'",
            },
            {
                "category": "declaration",
                "path": "blocks[0].children[1]",
                "message": "measure writes undeclared stream 'od'",
            },
        ],
    }


def _doc(workflow: dict[str, Any], roles: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_version": 1,
        "name": "t",
        "description": None,
        "roles": roles,
        "workflow": workflow,
    }


async def test_unsupported_schema_version_is_schema_diagnostic(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post(
        "/api/validate", json=_doc({"schema_version": 2, "blocks": []}, {})
    )
    assert resp.json() == {
        "ok": False,
        "diagnostics": [
            {
                "category": "schema",
                "path": "workflow",
                "message": "unsupported schema_version 2; expected 1",
            }
        ],
    }


async def test_bad_expression_grammar_is_schema_diagnostic(client: httpx.AsyncClient) -> None:
    workflow = {
        "schema_version": 1,
        "streams": {"od": {"units": "AU"}},
        "blocks": [
            {"loop": {
                "until": "mean(od[-3:]) > 0.6",
                "body": [{"wait": {"duration": "1s"}}],
            }},
        ],
    }
    resp = await client.post("/api/validate", json=_doc(workflow, {}))
    body = resp.json()
    assert body["ok"] is False
    assert len(body["diagnostics"]) == 1
    diag = body["diagnostics"][0]
    assert diag["category"] == "schema" and diag["path"] == "workflow"
    assert "unexpected character" in diag["message"]


def _parallel_stop(device_a: str, device_b: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "blocks": [
            {"parallel": {"children": [
                {"command": {"device": device_a, "verb": "stop"}},
                {"command": {"device": device_b, "verb": "stop"}},
            ]}},
        ],
    }


async def test_distinct_roles_of_same_type_get_distinct_placeholders(
    client: httpx.AsyncClient,
) -> None:
    roles = {"feed": {"type": "pump"}, "waste": {"type": "pump"}}
    resp = await client.post(
        "/api/validate", json=_doc(_parallel_stop("feed", "waste"), roles)
    )
    assert resp.json() == {"ok": True, "diagnostics": []}


async def test_same_role_in_parallel_lanes_hits_engine_affinity_check(
    client: httpx.AsyncClient,
) -> None:
    roles = {"feed": {"type": "pump"}}
    resp = await client.post(
        "/api/validate", json=_doc(_parallel_stop("feed", "feed"), roles)
    )
    body = resp.json()
    assert body["ok"] is False
    assert [d["category"] for d in body["diagnostics"]] == ["affinity"]
    assert body["diagnostics"][0]["path"] == "blocks[0]"


async def test_malformed_doc_is_422(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/validate", json={"doc_version": 1, "name": "x"})
    assert resp.status_code == 422


async def test_for_each_templated_roles_expand_before_substitution(
    client: httpx.AsyncClient,
) -> None:
    """A for_each body with a templated role (od_meter_{t}) must be expanded into
    concrete roles (od_meter_1, od_meter_2) BEFORE role substitution, or the mapping
    misses it (design §9)."""
    workflow = {
        "schema_version": 1,
        "streams": {"od_1": {"units": "AU"}, "od_2": {"units": "AU"}},
        "blocks": [
            {"for_each": {"var": "t", "in": [1, 2], "body": [
                {"measure": {"device": "od_meter_{t}", "verb": "measure", "into": "od_{t}"}},
            ]}},
        ],
    }
    roles = {"od_meter_1": {"type": "densitometer"}, "od_meter_2": {"type": "densitometer"}}
    resp = await client.post("/api/validate", json=_doc(workflow, roles))
    assert resp.json() == {"ok": True, "diagnostics": []}


async def test_malformed_for_each_yields_expansion_diagnostic(
    client: httpx.AsyncClient,
) -> None:
    """A malformed macro (empty for_each 'in') must not 500 — it surfaces as a
    validation diagnostic, same shape as the schema/engine diagnostics."""
    workflow = {
        "schema_version": 1,
        "blocks": [
            {"for_each": {"var": "t", "in": [], "body": [{"wait": {"duration": "1s"}}]}},
        ],
    }
    resp = await client.post("/api/validate", json=_doc(workflow, {}))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["diagnostics"] == [
        {
            "category": "expansion",
            "path": "workflow",
            "message": "for_each 'in' must be a non-empty list",
        }
    ]


async def test_non_object_group_ref_body_yields_diagnostic_not_500(
    client: httpx.AsyncClient,
) -> None:
    """A malformed group_ref (non-object body) must not 500 — it surfaces as a
    validation diagnostic, same shape as the schema/engine diagnostics."""
    workflow = {
        "schema_version": 1,
        "blocks": [
            {"group_ref": 42},
        ],
    }
    resp = await client.post("/api/validate", json=_doc(workflow, {}))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["diagnostics"]
