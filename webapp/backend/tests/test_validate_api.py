"""POST /api/validate: expand -> engine parse/validate -> path remap (design §4.3), against the
golden fixtures in webapp/fixtures/."""

import json
from pathlib import Path
from typing import Any

import httpx

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


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


async def test_morbidostat_example_is_clean(client: httpx.AsyncClient) -> None:
    """W9 acceptance (spec §8): the flagship example uses `groups` AND `for_each` and must
    validate with zero diagnostics through the real backend. Pins the source map's
    remap/dedup behaviour (one diagnostic per authored block, not one per for_each/group_ref
    expansion copy) against the real flagship, not just synthetic fixtures.

    Uses the real file, not a fixture copy — so this also pins that examples/morbidostat.json
    stays valid as the engine/backend evolve.
    """
    doc = json.loads((EXAMPLES / "morbidostat.json").read_text())
    resp = await client.post("/api/validate", json=doc)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "diagnostics": []}


async def test_doc_level_diagnostics(client: httpx.AsyncClient) -> None:
    """An unknown device type in `roles` is the engine's WorkflowLoadError now, surfaced as a
    single schema diagnostic (the old 3-way role_diagnostics is gone with roles.py)."""
    resp = await client.post("/api/validate", json=load_fixture("invalid-roles.json"))
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": False,
        "diagnostics": [
            {
                "category": "schema",
                "path": "workflow",
                "message": (
                    "role 'mixer': unknown device type 'stirrer'; "
                    "known types are ['densitometer', 'pump', 'valve']"
                ),
            }
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
            {"category": "params", "path": "blocks[0].children[0]",
             "message": "missing required param 'volume_ml' for verb 'dispense'"},
            {"category": "declaration", "path": "blocks[0].children[1]",
             "message": "measure writes undeclared stream 'od'"},
        ],
    }


def _doc(workflow: dict[str, Any], roles: dict[str, Any] | None = None) -> dict[str, Any]:
    wf = dict(workflow)
    if roles is not None:
        wf["roles"] = roles
    return {"doc_version": 1, "name": "t", "description": None, "workflow": wf}


async def test_schema_two_is_accepted(client: httpx.AsyncClient) -> None:
    """The former 'reject schema 2' test: schema 2 is now the supported version."""
    resp = await client.post("/api/validate", json=_doc({"schema_version": 2, "blocks": []}))
    assert resp.json() == {"ok": True, "diagnostics": []}


async def test_unsupported_schema_version_is_schema_diagnostic(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post("/api/validate", json=_doc({"schema_version": 3, "blocks": []}))
    body = resp.json()
    assert body["ok"] is False
    diag = body["diagnostics"][0]
    assert diag["category"] == "schema" and diag["path"] == "workflow"
    assert "unsupported schema_version 3; expected 2" in diag["message"]


async def test_bad_expression_grammar_is_schema_diagnostic(client: httpx.AsyncClient) -> None:
    workflow = {
        "schema_version": 2,
        "streams": {"od": {"units": "AU"}},
        "blocks": [
            {"loop": {"until": "mean(od[-3:]) > 0.6", "body": [{"wait": {"duration": "1s"}}]}},
        ],
    }
    resp = await client.post("/api/validate", json=_doc(workflow))
    body = resp.json()
    assert body["ok"] is False and len(body["diagnostics"]) == 1
    diag = body["diagnostics"][0]
    assert diag["category"] == "schema" and diag["path"] == "workflow"
    assert "unexpected character" in diag["message"]


def _parallel_stop(device_a: str, device_b: str) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "blocks": [
            {"parallel": {"children": [
                {"command": {"device": device_a, "verb": "stop"}},
                {"command": {"device": device_b, "verb": "stop"}},
            ]}},
        ],
    }


async def test_distinct_roles_of_same_type_are_clean(client: httpx.AsyncClient) -> None:
    roles = {"feed": {"type": "pump"}, "waste": {"type": "pump"}}
    resp = await client.post("/api/validate", json=_doc(_parallel_stop("feed", "waste"), roles))
    assert resp.json() == {"ok": True, "diagnostics": []}


async def test_same_role_in_parallel_lanes_hits_engine_affinity_check(
    client: httpx.AsyncClient,
) -> None:
    roles = {"feed": {"type": "pump"}}
    resp = await client.post("/api/validate", json=_doc(_parallel_stop("feed", "feed"), roles))
    body = resp.json()
    assert body["ok"] is False
    assert [d["category"] for d in body["diagnostics"]] == ["affinity"]
    assert body["diagnostics"][0]["path"] == "blocks[0]"


async def test_malformed_doc_is_422(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/validate", json={"doc_version": 1, "name": "x"})
    assert resp.status_code == 422


async def test_for_each_typed_role_var_validates_clean(client: httpx.AsyncClient) -> None:
    """A for_each over a typed role<densitometer> column replaces v1 od_meter_{t} string
    surgery (design §4). Concrete role names are declared, so it validates clean unbound (§5.4)."""
    workflow = {
        "schema_version": 2,
        "roles": {"od_meter_1": {"type": "densitometer"}, "od_meter_2": {"type": "densitometer"}},
        "streams": {"od_1": {"units": "AU"}, "od_2": {"units": "AU"}},
        "blocks": [
            {"for_each": {
                "vars": [
                    {"name": "meter", "kind": "role", "device_type": "densitometer"},
                    {"name": "od", "kind": "stream"},
                ],
                "in": [{"meter": "od_meter_1", "od": "od_1"}, {"meter": "od_meter_2", "od": "od_2"}],
                "body": [{"measure": {"device": "{meter}", "verb": "measure", "into": "{od}"}}],
            }},
        ],
    }
    resp = await client.post("/api/validate", json=_doc(workflow))
    assert resp.json() == {"ok": True, "diagnostics": []}


async def test_malformed_for_each_yields_expansion_diagnostic(client: httpx.AsyncClient) -> None:
    workflow = {
        "schema_version": 2,
        "blocks": [{"for_each": {
            "vars": [{"name": "t", "kind": "int"}], "in": [],
            "body": [{"wait": {"duration": "1s"}}],
        }}],
    }
    resp = await client.post("/api/validate", json=_doc(workflow))
    assert resp.status_code == 200
    assert resp.json() == {
        "ok": False,
        "diagnostics": [{"category": "expansion", "path": "workflow",
                         "message": "for_each 'in' must be a non-empty list"}],
    }


async def test_non_object_group_ref_body_yields_diagnostic_not_500(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post(
        "/api/validate", json=_doc({"schema_version": 2, "blocks": [{"group_ref": 42}]})
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False and body["diagnostics"]
