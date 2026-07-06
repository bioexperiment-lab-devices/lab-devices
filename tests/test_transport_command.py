import httpx
import pytest

from lab_devices import errors
from lab_devices.transport import Transport


def make_transport(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://lab")
    return Transport(client), client


async def test_success_returns_result():
    def handler(request: httpx.Request) -> httpx.Response:
        body = request.read().decode()
        import json

        env = json.loads(body)
        return httpx.Response(
            200, json={"id": env["id"], "status": "ok", "result": {"uptime_ms": 5}}
        )

    transport, client = make_transport(handler)
    try:
        result = await transport.command("pump_1", "ping")
        assert result == {"uptime_ms": 5}
    finally:
        await client.aclose()


async def test_device_error_raises_mapped_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        env = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "id": env["id"],
                "status": "error",
                "error": {"code": "invalid_params", "message": "bad", "details": {"param": "x"}},
            },
        )

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.InvalidParamsError):
            await transport.command("pump_1", "dispense", {"volume_ml": -1})
    finally:
        await client.aclose()


async def test_unreachable_503_maps_from_envelope():
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        env = json.loads(request.read())
        return httpx.Response(
            503,
            json={
                "id": env["id"],
                "status": "error",
                "error": {"code": "device_unreachable", "message": "no"},
            },
        )

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.DeviceUnreachableError):
            await transport.command("pump_1", "status")
    finally:
        await client.aclose()


async def test_id_mismatch_raises_protocol_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "WRONG", "status": "ok", "result": {}})

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.LabProtocolError):
            await transport.command("pump_1", "ping")
    finally:
        await client.aclose()


async def test_oversize_body_rejected_before_send():
    sent = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal sent
        sent = True
        return httpx.Response(200, json={})

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.LabProtocolError):
            await transport.command("pump_1", "x", {"blob": "a" * 40000})
        assert sent is False
    finally:
        await client.aclose()
