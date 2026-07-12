"""WebSocket contract: live stream, replay, terminal close, 4404. See design §7.5."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from httpx_ws import WebSocketDisconnect, aconnect_ws

import runsupport


async def _create_and_start(api: SimpleNamespace, blocks: list) -> str:
    response = await api.client.post("/api/experiments", json=runsupport.make_doc(blocks))
    experiment_id = response.json()["id"]
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


async def _collect_until_terminal(ws: Any) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    while True:
        message = await asyncio.wait_for(ws.receive_json(), timeout=5)
        messages.append(message)
        if message["type"] == "status" and message["status"] in runsupport.TERMINAL:
            return messages


async def test_ws_streams_run_to_terminal_status(api: SimpleNamespace) -> None:
    run_id = await _create_and_start(api, runsupport.HAPPY_BLOCKS)
    async with aconnect_ws(
        f"http://studio/api/runs/{run_id}/events",
        api.client,
        keepalive_ping_interval_seconds=None,
    ) as ws:
        messages = await _collect_until_terminal(ws)
    assert [m["seq"] for m in messages] == list(range(len(messages)))
    assert messages[0] == {"type": "status", "seq": 0, "status": "running"}
    events = [m for m in messages if m["type"] == "event"]
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "run_started"
    assert "measure_recorded" in kinds
    assert kinds[-1] == "run_finished"
    assert messages[-1]["status"] == "completed"
    measure = next(e for e in events if e["kind"] == "measure_recorded")
    assert set(measure) == {"type", "seq", "timestamp", "kind", "block_id", "data"}
    assert measure["data"]["stream"] == "od"


async def test_ws_replays_from_since(api: SimpleNamespace) -> None:
    run_id = await _create_and_start(api, runsupport.HAPPY_BLOCKS)
    task = api.manager.current_task()
    assert task is not None
    await asyncio.wait_for(task, 10)
    async with aconnect_ws(
        f"http://studio/api/runs/{run_id}/events",
        api.client,
        keepalive_ping_interval_seconds=None,
    ) as ws:
        full = await _collect_until_terminal(ws)
    since = full[2]["seq"]
    async with aconnect_ws(
        f"http://studio/api/runs/{run_id}/events?since={since}",
        api.client,
        keepalive_ping_interval_seconds=None,
    ) as ws:
        tail = await _collect_until_terminal(ws)
    assert tail == full[3:]


async def test_ws_unknown_run_closes_4404(api: SimpleNamespace) -> None:
    # httpx-ws 0.9.0 raises WebSocketDisconnect on receive() when the server closes,
    # but aconnect_ws's __aexit__ runs that receive inside an anyio TaskGroup, so it
    # surfaces from the `async with` block as a single-exception ExceptionGroup rather
    # than a bare WebSocketDisconnect (observed: anyio 4.14, Python 3.14).
    with pytest.raises(ExceptionGroup) as info:
        async with aconnect_ws(
            "http://studio/api/runs/ghost/events",
            api.client,
            keepalive_ping_interval_seconds=None,
        ) as ws:
            await asyncio.wait_for(ws.receive_json(), timeout=5)
    (disconnect,) = info.value.exceptions
    assert isinstance(disconnect, WebSocketDisconnect)
    assert disconnect.code == 4404


async def test_ws_sees_input_lifecycle(api: SimpleNamespace) -> None:
    run_id = await _create_and_start(api, runsupport.INPUT_BLOCKS)
    async with aconnect_ws(
        f"http://studio/api/runs/{run_id}/events",
        api.client,
        keepalive_ping_interval_seconds=None,
    ) as ws:
        # drain until the engine asks for input
        while True:
            message = await asyncio.wait_for(ws.receive_json(), timeout=5)
            if message["type"] == "event" and message["kind"] == "input_requested":
                break
        response = await api.client.post(f"/api/runs/{run_id}/input", json={"value": 3})
        assert response.status_code == 204
        messages = await _collect_until_terminal(ws)
    kinds = [m.get("kind") for m in messages if m["type"] == "event"]
    assert "input_bound" in kinds
    assert messages[-1]["status"] == "completed"
