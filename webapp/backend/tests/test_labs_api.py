"""Labs endpoints against MockTransport-backed registry and agent clients."""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI

from lab_devices.client import LabClient
from lab_devices.discovery import LabInfo, LabRegistry

from experiment_studio.api.labs import get_labs_service
from experiment_studio.labs import LabsService

ROSTER = {
    "khamit_desktop": {"host": "127.0.0.1", "port": 8089},
    "protres_ksenios": {"host": "127.0.0.1", "port": 8081},
}
AGENT_DEVICES = {
    "devices": [
        {
            "id": "pump_1",
            "type": "pump",
            "port": "COM3",
            "connected": True,
            "identify": {"model": "P-100", "firmware_version": "2.1.0"},
        },
        {"id": "valve_2", "type": "valve", "port": "COM4", "connected": False},
    ]
}


def _registry() -> LabRegistry:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=ROSTER)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LabRegistry(url="http://siteapp:8000/api/clients/", http=http)


def _agent_factory(response_for: dict[str, httpx.Response | Exception]):
    """Map 'METHOD /path' -> canned response (or exception to raise)."""

    def factory(info: LabInfo) -> LabClient:
        def handler(request: httpx.Request) -> httpx.Response:
            key = f"{request.method} {request.url.path}"
            outcome = response_for.get(key)
            if outcome is None:
                return httpx.Response(404, json={})
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=f"http://{info.host}:{info.port}",
        )
        return LabClient(info.host, info.port, http=http)

    return factory


async def _probe_all_online(name: str) -> bool:
    return True


def _install(app: FastAPI, service: LabsService) -> None:
    app.dependency_overrides[get_labs_service] = lambda: service


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


async def test_list_labs_with_online_flag(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    resp = await client.get("/api/labs")
    assert resp.status_code == 200
    labs = {lab["name"]: lab for lab in resp.json()}
    assert labs["khamit_desktop"] == {
        "name": "khamit_desktop",
        "host": "127.0.0.1",
        "port": 8089,
        "online": True,
    }
    assert set(labs) == {"khamit_desktop", "protres_ksenios"}


async def test_devices_serialization(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    resp = await client.get("/api/labs/khamit_desktop/devices")
    assert resp.status_code == 200
    pump, valve = resp.json()
    assert pump == {
        "id": "pump_1",
        "type": "pump",
        "port": "COM3",
        "connected": True,
        "model": "P-100",
        "firmware": "2.1.0",
    }
    assert valve["model"] is None and valve["firmware"] is None


async def test_discover_returns_devices(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    resp = await client.post("/api/labs/khamit_desktop/discover")
    assert resp.status_code == 200
    assert [d["id"] for d in resp.json()] == ["pump_1", "valve_2"]


async def test_unknown_lab_is_404(
    app: FastAPI, client: httpx.AsyncClient, happy_service: LabsService
) -> None:
    _install(app, happy_service)
    resp = await client.get("/api/labs/ghost/devices")
    assert resp.status_code == 404
    assert resp.json()["code"] == "unknown_lab"


async def test_agent_unreachable_is_502(app: FastAPI, client: httpx.AsyncClient) -> None:
    def factory(info: LabInfo) -> LabClient:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom", request=request)

        http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=f"http://{info.host}:{info.port}",
        )
        return LabClient(info.host, info.port, http=http)

    service = LabsService(_registry(), client_factory=factory, probe=_probe_all_online)
    _install(app, service)
    try:
        resp = await client.get("/api/labs/khamit_desktop/devices")
        assert resp.status_code == 502
        assert resp.json()["code"] == "lab_unreachable"
    finally:
        await service.aclose()


async def test_discover_busy_agent_is_409(app: FastAPI, client: httpx.AsyncClient) -> None:
    service = LabsService(
        _registry(),
        client_factory=_agent_factory(
            {
                "POST /api/v1/discover": httpx.Response(
                    409, json={"error": "discovery in progress"}
                )
            }
        ),
        probe=_probe_all_online,
    )
    _install(app, service)
    try:
        resp = await client.post("/api/labs/khamit_desktop/discover")
        assert resp.status_code == 409
        assert resp.json()["code"] == "agent_busy"
    finally:
        await service.aclose()


async def test_devices_malformed_agent_body_is_502_lab_error(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    service = LabsService(
        _registry(),
        client_factory=_agent_factory(
            {"GET /api/v1/devices": httpx.Response(500, text="internal agent meltdown")}
        ),
        probe=_probe_all_online,
    )
    _install(app, service)
    try:
        resp = await client.get("/api/labs/khamit_desktop/devices")
        assert resp.status_code == 502
        assert resp.json()["code"] == "lab_error"
    finally:
        await service.aclose()
