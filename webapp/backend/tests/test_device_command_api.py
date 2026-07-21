"""Generic device command passthrough, run-active guard, job status, error codes."""

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from lab_devices.client import LabClient
from experiment_studio.api.deps import get_run_manager
from experiment_studio.labs import LabsService
from tests.test_labs_api import _agent_factory, _install, _probe_all_online, _registry


def _ok(result: object) -> httpx.Response:
    return httpx.Response(200, json={"id": "", "status": "ok", "result": result})


@pytest.fixture
async def ping_service() -> AsyncIterator[LabsService]:
    service = LabsService(
        _registry(),
        client_factory=_agent_factory(
            {"POST /api/v1/devices/pump_1/command": _ok({"uptime_ms": 42133})}
        ),
        probe=_probe_all_online,
    )
    yield service
    await service.aclose()


async def test_command_returns_result(
    app: FastAPI, client: httpx.AsyncClient, ping_service: LabsService
) -> None:
    _install(app, ping_service)
    resp = await client.post(
        "/api/labs/khamit_desktop/devices/pump_1/command",
        json={"cmd": "ping", "params": None},
    )
    assert resp.status_code == 200
    assert resp.json() == {"result": {"uptime_ms": 42133}}


async def test_command_forwards_params(app: FastAPI, client: httpx.AsyncClient) -> None:
    seen: dict[str, object] = {}

    def factory(info: object) -> LabClient:
        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(json.loads(request.content))
            return _ok({"job_id": "j1"})

        http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url=f"http://{info.host}:{info.port}",  # type: ignore[attr-defined]
        )
        return LabClient(info.host, info.port, http=http)  # type: ignore[attr-defined]

    service = LabsService(_registry(), client_factory=factory, probe=_probe_all_online)
    _install(app, service)
    try:
        resp = await client.post(
            "/api/labs/khamit_desktop/devices/pump_1/command",
            json={"cmd": "dispense", "params": {"volume_ml": 10, "direction": "forward"}},
        )
        assert resp.status_code == 200
        assert resp.json() == {"result": {"job_id": "j1"}}
        assert seen["cmd"] == "dispense"
        assert seen["params"] == {"volume_ml": 10, "direction": "forward"}
    finally:
        await service.aclose()


async def test_command_blocked_during_active_run(
    app: FastAPI, client: httpx.AsyncClient, ping_service: LabsService
) -> None:
    _install(app, ping_service)
    stub = SimpleNamespace(
        active=lambda: SimpleNamespace(lab="khamit_desktop", run_id="r1")
    )
    app.dependency_overrides[get_run_manager] = lambda: stub
    try:
        resp = await client.post(
            "/api/labs/khamit_desktop/devices/pump_1/command",
            json={"cmd": "ping", "params": None},
        )
        assert resp.status_code == 409
        assert resp.json()["code"] == "run_active"
    finally:
        del app.dependency_overrides[get_run_manager]


async def test_command_allowed_when_run_is_on_another_lab(
    app: FastAPI, client: httpx.AsyncClient, ping_service: LabsService
) -> None:
    _install(app, ping_service)
    stub = SimpleNamespace(active=lambda: SimpleNamespace(lab="other_lab", run_id="r1"))
    app.dependency_overrides[get_run_manager] = lambda: stub
    try:
        resp = await client.post(
            "/api/labs/khamit_desktop/devices/pump_1/command",
            json={"cmd": "ping", "params": None},
        )
        assert resp.status_code == 200
    finally:
        del app.dependency_overrides[get_run_manager]


def _err(code: str, message: str) -> httpx.Response:
    return httpx.Response(
        200, json={"id": "", "status": "error", "error": {"code": code, "message": message}}
    )


@pytest.mark.parametrize(
    ("code", "status", "envelope_code"),
    [
        ("busy", 409, "agent_busy"),
        ("invalid_params", 422, "invalid_params"),
        ("unknown_command", 400, "unknown_command"),
        ("not_calibrated", 409, "not_ready"),
    ],
)
async def test_command_error_codes(
    app: FastAPI,
    client: httpx.AsyncClient,
    code: str,
    status: int,
    envelope_code: str,
) -> None:
    service = LabsService(
        _registry(),
        client_factory=_agent_factory(
            {"POST /api/v1/devices/pump_1/command": _err(code, "device said no")}
        ),
        probe=_probe_all_online,
    )
    _install(app, service)
    try:
        resp = await client.post(
            "/api/labs/khamit_desktop/devices/pump_1/command",
            json={"cmd": "dispense", "params": {"volume_ml": 10}},
        )
        assert resp.status_code == status
        assert resp.json()["code"] == envelope_code
    finally:
        await service.aclose()


async def test_job_status_returns_result(app: FastAPI, client: httpx.AsyncClient) -> None:
    service = LabsService(
        _registry(),
        client_factory=_agent_factory(
            {
                "POST /api/v1/devices/densitometer_1/command": _ok(
                    {"job_id": "j9", "status": "succeeded", "result": {"od": 0.42}}
                )
            }
        ),
        probe=_probe_all_online,
    )
    _install(app, service)
    try:
        resp = await client.get("/api/labs/khamit_desktop/devices/densitometer_1/jobs/j9")
        assert resp.status_code == 200
        assert resp.json()["result"]["status"] == "succeeded"
    finally:
        await service.aclose()
