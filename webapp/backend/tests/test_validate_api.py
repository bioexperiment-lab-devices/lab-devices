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
    assert resp.json() == {"ok": True, "diagnostics": [], "binding_types": {}}


async def test_valid_control_blocks_doc_is_clean(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/validate", json=load_fixture("valid-control-blocks.json"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["diagnostics"] == []
    # emergency_stop is an operator_input bool; V/c are numeric-literal computes the engine
    # does not type (it only types string-valued computes), so they may be absent.
    assert body["binding_types"]["emergency_stop"] == {"base": "bool", "unit": "unitless"}


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
    body = resp.json()
    assert body["ok"] is True and body["diagnostics"] == []
    assert body["binding_types"]["working_volume_ml"] == {"base": "int", "unit": "unitless"}
    assert body["binding_types"]["od_min"] == {"base": "number", "unit": "unitless"}


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
        "binding_types": {},
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
        "binding_types": {},
    }


def _doc(workflow: dict[str, Any], roles: dict[str, Any] | None = None) -> dict[str, Any]:
    wf = dict(workflow)
    if roles is not None:
        wf["roles"] = roles
    return {"doc_version": 1, "name": "t", "description": None, "workflow": wf}


async def test_schema_three_is_accepted(client: httpx.AsyncClient) -> None:
    """Schema 3 is the supported version (statically typed, unit-checked)."""
    resp = await client.post("/api/validate", json=_doc({"schema_version": 3, "blocks": []}))
    assert resp.json() == {"ok": True, "diagnostics": [], "binding_types": {}}


async def test_unsupported_schema_version_is_schema_diagnostic(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post("/api/validate", json=_doc({"schema_version": 2, "blocks": []}))
    body = resp.json()
    assert body["ok"] is False
    diag = body["diagnostics"][0]
    assert diag["category"] == "schema" and diag["path"] == "workflow"
    assert "unsupported schema_version 2; expected 3" in diag["message"]


async def test_bad_expression_grammar_is_schema_diagnostic(client: httpx.AsyncClient) -> None:
    workflow = {
        "schema_version": 3,
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
        "schema_version": 3,
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
    assert resp.json() == {"ok": True, "diagnostics": [], "binding_types": {}}


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
        "schema_version": 3,
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
    assert resp.json() == {"ok": True, "diagnostics": [], "binding_types": {}}


async def test_malformed_for_each_yields_expansion_diagnostic(client: httpx.AsyncClient) -> None:
    workflow = {
        "schema_version": 3,
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
        "binding_types": {},
    }


async def test_non_object_group_ref_body_yields_diagnostic_not_500(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post(
        "/api/validate", json=_doc({"schema_version": 3, "blocks": [{"group_ref": 42}]})
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False and body["diagnostics"]


async def test_validate_returns_binding_types(client: httpx.AsyncClient) -> None:
    workflow = {
        "schema_version": 3,
        "blocks": [
            {"operator_input": {"name": "n", "type": "int"}},
            {"compute": {"into": "rate", "value": "1", "as": "AU/s"}},
        ],
    }
    resp = await client.post("/api/validate", json=_doc(workflow))
    body = resp.json()
    assert body["binding_types"]["n"] == {"base": "int", "unit": "unitless"}
    assert body["binding_types"]["rate"] == {"base": "int", "unit": "AU/s"}


async def test_binding_types_empty_when_doc_fails_to_load(client: httpx.AsyncClient) -> None:
    # unknown device type -> WorkflowLoadError -> no types, but diagnostics still returned
    resp = await client.post("/api/validate", json=load_fixture("invalid-roles.json"))
    body = resp.json()
    assert body["binding_types"] == {}
    assert body["ok"] is False and body["diagnostics"]


async def test_validate_surfaces_constants(client: httpx.AsyncClient) -> None:
    """A workflow-global constant survives expand and is typed into `binding_types` just like
    an operator_input/compute binding (constants design §5)."""
    workflow = {
        "schema_version": 3,
        "constants": {"MAX_TEMP": {"value": 37.0, "as": "celsius"}},
        "blocks": [],
    }
    resp = await client.post("/api/validate", json=_doc(workflow))
    body = resp.json()
    assert body["ok"] is True and body["diagnostics"] == []
    assert body["binding_types"]["MAX_TEMP"] == {"base": "number", "unit": "celsius"}


async def test_valid_constants_fixture(client: httpx.AsyncClient) -> None:
    """End-to-end golden fixture (constants design §5, task 13): a plain literal (`DOSES`), a
    unit'd literal (`MAX_TEMP`), and a constant derived from an earlier one (`TOTAL_ML`), the
    derived one read by both a `compute` and (transitively) an `alarm` guard. Exercises the
    same expand -> engine parse/validate -> binding_types path as the other fixtures above,
    end to end through the real backend rather than an inline workflow dict."""
    resp = await client.post("/api/validate", json=load_fixture("valid-constants.json"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["diagnostics"] == []
    assert body["binding_types"]["MAX_TEMP"] == {"base": "number", "unit": "celsius"}
    assert body["binding_types"]["TOTAL_ML"]["base"] == "number"
