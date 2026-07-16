"""Experiments CRUD endpoints at the ASGI level (design §6)."""

import json
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI

import runsupport
from experiment_studio.records import RecordsStore


def doc_payload(name: str = "OD growth curve", **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "doc_version": 1,
        "name": name,
        "description": None,
        "roles": {"feed_pump": {"type": "pump"}},
        "workflow": {"schema_version": 1, "blocks": []},
    }
    payload.update(overrides)
    return payload


async def test_crud_roundtrip(client: httpx.AsyncClient) -> None:
    created = await client.post("/api/experiments", json=doc_payload())
    assert created.status_code == 201
    body = created.json()
    exp_id = body["id"]
    assert body["name"] == "OD growth curve"
    assert body["doc"]["workflow"] == {"schema_version": 1, "blocks": []}

    listed = await client.get("/api/experiments")
    assert listed.status_code == 200
    assert [e["name"] for e in listed.json()] == ["OD growth curve"]
    assert "doc" not in listed.json()[0]

    fetched = await client.get(f"/api/experiments/{exp_id}")
    assert fetched.status_code == 200
    assert fetched.json() == body

    replaced = await client.put(
        f"/api/experiments/{exp_id}", json=doc_payload("renamed", description="v2")
    )
    assert replaced.status_code == 200
    assert replaced.json()["name"] == "renamed"
    assert replaced.json()["description"] == "v2"

    deleted = await client.delete(f"/api/experiments/{exp_id}")
    assert deleted.status_code == 204
    assert (await client.get(f"/api/experiments/{exp_id}")).status_code == 404


async def test_name_conflict_is_409(client: httpx.AsyncClient) -> None:
    assert (await client.post("/api/experiments", json=doc_payload("X"))).status_code == 201
    conflict = await client.post("/api/experiments", json=doc_payload("X"))
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "name_conflict"

    other = await client.post("/api/experiments", json=doc_payload("Y"))
    put = await client.put(
        f"/api/experiments/{other.json()['id']}", json=doc_payload("X")
    )
    assert put.status_code == 409
    assert put.json()["code"] == "name_conflict"


async def test_unknown_experiment_is_404(client: httpx.AsyncClient) -> None:
    for resp in (
        await client.get("/api/experiments/ghost"),
        await client.put("/api/experiments/ghost", json=doc_payload()),
        await client.delete("/api/experiments/ghost"),
        await client.post("/api/experiments/ghost/duplicate"),
    ):
        assert resp.status_code == 404
        assert resp.json()["code"] == "unknown_experiment"


async def test_duplicate_suffixes_name(client: httpx.AsyncClient) -> None:
    src = await client.post("/api/experiments", json=doc_payload("X"))
    first = await client.post(f"/api/experiments/{src.json()['id']}/duplicate")
    second = await client.post(f"/api/experiments/{src.json()['id']}/duplicate")
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["name"] == "X (copy)"
    assert second.json()["name"] == "X (copy 2)"


async def test_malformed_doc_is_422(client: httpx.AsyncClient) -> None:
    for bad in (
        doc_payload(doc_version=2),
        doc_payload(name=""),
        {k: v for k, v in doc_payload().items() if k != "workflow"},
    ):
        resp = await client.post("/api/experiments", json=bad)
        assert resp.status_code == 422


async def test_experiment_mappings_endpoint(
    client: httpx.AsyncClient, app: FastAPI, tmp_path: Path
) -> None:
    doc = runsupport.make_doc(runsupport.HAPPY_BLOCKS)
    created = (await client.post("/api/experiments", json=doc)).json()
    resp = await client.get(f"/api/experiments/{created['id']}/mappings/lab_a")
    assert resp.status_code == 200 and resp.json() == {}
    store = RecordsStore(app.state.db, tmp_path)
    await store.save_mapping(created["id"], "lab_a", {"feed": "pump_1"})
    resp = await client.get(f"/api/experiments/{created['id']}/mappings/lab_a")
    assert resp.json() == {"feed": "pump_1"}
    resp = await client.get("/api/experiments/nope/mappings/lab_a")
    assert resp.status_code == 404 and resp.json()["code"] == "unknown_experiment"


async def test_import_creates_and_is_retrievable(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/experiments/import", json=doc_payload("Imported"))
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Imported"
    fetched = await client.get(f"/api/experiments/{body['id']}")
    assert fetched.status_code == 200 and fetched.json() == body


async def test_import_auto_renames_instead_of_conflicting(
    client: httpx.AsyncClient,
) -> None:
    """§5.2: import never 409s — it walks the suffix like duplicate does."""
    first = await client.post("/api/experiments/import", json=doc_payload("X"))
    second = await client.post("/api/experiments/import", json=doc_payload("X"))
    third = await client.post("/api/experiments/import", json=doc_payload("X"))
    assert [r.status_code for r in (first, second, third)] == [201, 201, 201]
    assert first.json()["name"] == "X"
    assert second.json()["name"] == "X (copy)"
    assert third.json()["name"] == "X (copy 2)"
    assert second.json()["doc"]["name"] == "X (copy)"


async def test_import_malformed_is_422(client: httpx.AsyncClient) -> None:
    for bad in (
        doc_payload(doc_version=2),
        doc_payload(name=""),
        {k: v for k, v in doc_payload().items() if k != "workflow"},
    ):
        resp = await client.post("/api/experiments/import", json=bad)
        assert resp.status_code == 422


async def test_import_does_not_gate_on_workflow_validity(
    client: httpx.AsyncClient,
) -> None:
    """§5.2: import is a save. Parent spec §4.3 — validation never blocks saving, only
    running."""
    broken = doc_payload(
        "Broken",
        workflow={
            "schema_version": 1,
            "blocks": [{"command": {"device": "ghost_role", "verb": "no_such_verb"}}],
        },
    )
    resp = await client.post("/api/experiments/import", json=broken)
    assert resp.status_code == 201
    assert resp.json()["doc"]["workflow"]["blocks"][0]["command"]["verb"] == (
        "no_such_verb"
    )


async def test_import_roundtrips_the_real_morbidostat_example(
    client: httpx.AsyncClient,
) -> None:
    """The load-bearing guarantee (§8): the shipped examples import byte-for-byte.

    Uses the real file, not a fixture — so this also pins that examples/*.json stay
    importable.
    """
    path = Path(__file__).parents[3] / "examples" / "morbidostat.json"
    original = json.loads(path.read_text())
    resp = await client.post("/api/experiments/import", json=original)
    assert resp.status_code == 201
    fetched = await client.get(f"/api/experiments/{resp.json()['id']}")
    assert fetched.json()["doc"] == original
