"""HTTP layer for runs: envelopes, status codes, controls, input. See design §6."""

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx

import runsupport


async def _create_experiment(api: SimpleNamespace, blocks: list, **kw: Any) -> str:
    response = await api.client.post("/api/experiments", json=runsupport.make_doc(blocks, **kw))
    assert response.status_code == 201
    return str(response.json()["id"])


async def _start(api: SimpleNamespace, blocks: list, **kw: Any) -> str:
    experiment_id = await _create_experiment(api, blocks, **kw)
    response = await api.client.post(
        "/api/runs",
        json={
            "experiment_id": experiment_id,
            "lab": runsupport.LAB,
            "role_mapping": runsupport.MAPPING,
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["run_id"])


async def _finish(api: SimpleNamespace, timeout: float = 10.0) -> None:
    task = api.manager.current_task()
    assert task is not None
    await asyncio.wait_for(task, timeout)


async def _wait_pending_input(api: SimpleNamespace) -> dict[str, Any]:
    async with asyncio.timeout(5):
        while True:
            response = await api.client.get("/api/runs/active")
            body = response.json()
            if body and body.get("pending_input"):
                return dict(body)
            await asyncio.sleep(0.005)


async def _wait_for_job(api: SimpleNamespace) -> None:
    """Poll until the background run task has actually issued a job (Task 4 finding:
    start() no longer awaits anything after create_task, so the task isn't guaranteed
    to have run at all by the time POST /api/runs returns)."""
    async with asyncio.timeout(5):
        while not api.fake.jobs:
            await asyncio.sleep(0.005)


async def test_start_returns_run_id_and_active_payload(api: SimpleNamespace) -> None:
    api.fake.hold_job("dispense")
    run_id = await _start(api, runsupport.HAPPY_BLOCKS)
    response = await api.client.get("/api/runs/active")
    body = response.json()
    assert body["run_id"] == run_id
    assert body["status"] == "running"
    assert body["experiment"]["name"] == "Growth run"
    assert body["seq"] >= 0
    assert body["pending_input"] is None
    await _wait_for_job(api)
    api.fake.complete_job("j-1")
    await _finish(api)
    response = await api.client.get("/api/runs/active")
    assert response.json() is None


async def test_second_run_409_with_active_run_id(api: SimpleNamespace) -> None:
    api.fake.hold_job("dispense")
    run_id = await _start(api, runsupport.HAPPY_BLOCKS)
    experiment_id = await _create_experiment(api, runsupport.HAPPY_BLOCKS, name="Other")
    response = await api.client.post(
        "/api/runs",
        json={
            "experiment_id": experiment_id,
            "lab": runsupport.LAB,
            "role_mapping": runsupport.MAPPING,
        },
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "run_active"
    assert body["active_run_id"] == run_id
    assert "detail" in body
    await _wait_for_job(api)
    api.fake.complete_job("j-1")
    await _finish(api)


async def test_preflight_422_with_diagnostics(api: SimpleNamespace) -> None:
    experiment_id = await _create_experiment(api, runsupport.HAPPY_BLOCKS)
    response = await api.client.post(
        "/api/runs",
        json={
            "experiment_id": experiment_id,
            "lab": runsupport.LAB,
            "role_mapping": {"feed": "pump_1"},
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "preflight_failed"
    assert body["diagnostics"][0]["category"] == "mapping"


async def test_validation_422_with_record_id(api: SimpleNamespace) -> None:
    experiment_id = await _create_experiment(api, runsupport.INVALID_BLOCKS)
    response = await api.client.post(
        "/api/runs",
        json={
            "experiment_id": experiment_id,
            "lab": runsupport.LAB,
            "role_mapping": runsupport.MAPPING,
        },
    )
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_failed"
    assert body["diagnostics"]
    record = await api.client.get(f"/api/records/{body['record_id']}")
    assert record.status_code == 200
    assert record.json()["status"] == "failed"


async def test_unknown_experiment_and_lab_404(api: SimpleNamespace) -> None:
    response = await api.client.post(
        "/api/runs",
        json={"experiment_id": "nope", "lab": runsupport.LAB, "role_mapping": {}},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_experiment"
    experiment_id = await _create_experiment(api, runsupport.HAPPY_BLOCKS)
    response = await api.client.post(
        "/api/runs",
        json={
            "experiment_id": experiment_id,
            "lab": "ghost-lab",
            "role_mapping": runsupport.MAPPING,
        },
    )
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_lab"


async def test_pause_resume_abort_endpoints(api: SimpleNamespace) -> None:
    api.fake.hold_job("dispense")
    run_id = await _start(api, runsupport.HAPPY_BLOCKS)
    assert (await api.client.post(f"/api/runs/{run_id}/pause")).status_code == 204
    body = (await api.client.get("/api/runs/active")).json()
    assert body["status"] == "paused"
    assert (await api.client.post(f"/api/runs/{run_id}/resume")).status_code == 204
    assert (await api.client.post(f"/api/runs/{run_id}/abort")).status_code == 204
    assert (await api.client.post(f"/api/runs/{run_id}/abort")).status_code == 204
    await _wait_for_job(api)
    api.fake.complete_job("j-1")
    await _finish(api)
    # 404 for a non-active run id (§6)
    assert (await api.client.post(f"/api/runs/{run_id}/pause")).status_code == 404
    assert (await api.client.post(f"/api/runs/{run_id}/pause")).json()["code"] == "unknown_run"


async def test_input_endpoint_flow(api: SimpleNamespace) -> None:
    run_id = await _start(api, runsupport.INPUT_BLOCKS)
    body = await _wait_pending_input(api)
    assert body["pending_input"]["name"] == "target"
    response = await api.client.post(f"/api/runs/{run_id}/input", json={"value": 99})
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_value"
    response = await api.client.post(f"/api/runs/{run_id}/input", json={"value": 7})
    assert response.status_code == 204
    await _finish(api)
    response = await api.client.post(f"/api/runs/{run_id}/input", json={"value": 7})
    assert response.status_code == 404  # run no longer active


async def test_input_409_when_none_pending(api: SimpleNamespace) -> None:
    api.fake.hold_job("dispense")
    run_id = await _start(api, runsupport.HAPPY_BLOCKS)
    response = await api.client.post(f"/api/runs/{run_id}/input", json={"value": 1})
    assert response.status_code == 409
    assert response.json()["code"] == "no_pending_input"
    await _wait_for_job(api)
    api.fake.complete_job("j-1")
    await _finish(api)


async def test_discover_409_while_run_active_on_that_lab(api: SimpleNamespace) -> None:
    """§6: POST /api/labs/{lab}/discover refuses while a run is active on that lab."""
    api.fake.hold_job("dispense")
    await _start(api, runsupport.HAPPY_BLOCKS)
    response = await api.client.post(f"/api/labs/{runsupport.LAB}/discover")
    assert response.status_code == 409
    assert response.json()["code"] == "run_active"
    await _wait_for_job(api)
    api.fake.complete_job("j-1")
    await _finish(api)


async def test_run_artifacts_via_records_endpoints(api: SimpleNamespace) -> None:
    run_id = await _start(api, runsupport.HAPPY_BLOCKS)
    await _finish(api)
    events = (await api.client.get(f"/api/records/{run_id}/events")).json()
    assert [e["kind"] for e in events][0] == "run_started"
    streams = (await api.client.get(f"/api/records/{run_id}/streams")).json()
    assert streams["od"]["units"] == "AU"
    assert len(streams["od"]["t"]) == len(streams["od"]["v"]) == 1
    record = (await api.client.get(f"/api/records/{run_id}")).json()
    assert record["status"] == "completed"
    assert record["report"]["status"] == "completed"
    assert record["doc"]["doc_version"] == 1


async def test_body_shape_422_is_normalized(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/runs", json={"experiment_id": "x", "lab": "lab_a"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "invalid_request"
    assert isinstance(body["detail"], str) and "role_mapping" in body["detail"]
