"""Name endpoint + name-merge into the devices/discover payloads."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from experiment_studio.labs import LabsService
from tests.test_labs_api import (
    AGENT_DEVICES,
    _agent_factory,
    _install,
    _probe_all_online,
    _registry,
)


@pytest.fixture
async def happy_service() -> AsyncIterator[LabsService]:
    service = LabsService(
        _registry(),
        client_factory=_agent_factory(
            {
                "GET /api/v1/devices": httpx.Response(200, json=AGENT_DEVICES),
                "POST /api/v1/discover": httpx.Response(200, json=AGENT_DEVICES),
            }
        ),
        probe=_probe_all_online,
    )
    yield service
    await service.aclose()


async def test_devices_have_null_name_by_default(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    resp = await client.get("/api/labs/khamit_desktop/devices")
    assert resp.status_code == 200
    assert all(d["name"] is None for d in resp.json())


async def test_put_name_then_devices_shows_it(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    put = await client.put(
        "/api/labs/khamit_desktop/devices/pump_1/name", json={"name": "Culture pump"}
    )
    assert put.status_code == 200
    assert put.json() == {"name": "Culture pump"}

    resp = await client.get("/api/labs/khamit_desktop/devices")
    by_id = {d["id"]: d for d in resp.json()}
    assert by_id["pump_1"]["name"] == "Culture pump"
    assert by_id["valve_2"]["name"] is None


async def test_discover_also_merges_names(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    await client.put(
        "/api/labs/khamit_desktop/devices/pump_1/name", json={"name": "Culture pump"}
    )
    resp = await client.post("/api/labs/khamit_desktop/discover")
    by_id = {d["id"]: d for d in resp.json()}
    assert by_id["pump_1"]["name"] == "Culture pump"


async def test_empty_name_clears(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    await client.put(
        "/api/labs/khamit_desktop/devices/pump_1/name", json={"name": "Culture pump"}
    )
    cleared = await client.put(
        "/api/labs/khamit_desktop/devices/pump_1/name", json={"name": "   "}
    )
    assert cleared.json() == {"name": None}
    resp = await client.get("/api/labs/khamit_desktop/devices")
    by_id = {d["id"]: d for d in resp.json()}
    assert by_id["pump_1"]["name"] is None
