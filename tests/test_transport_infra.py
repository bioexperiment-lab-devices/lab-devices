import httpx
import pytest

from lab_devices import errors
from lab_devices.transport import Transport


def make_transport(handler):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://lab")
    return Transport(client), client


async def test_get_devices_returns_body():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/devices"
        return httpx.Response(200, json={"devices": [], "discovered_at": None})

    transport, client = make_transport(handler)
    try:
        body = await transport.get_devices()
        assert body["devices"] == []
    finally:
        await client.aclose()


async def test_discover_409_discovery_in_progress():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": "discovery in progress"})

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.DiscoveryInProgressError):
            await transport.discover()
    finally:
        await client.aclose()


async def test_discover_409_job_in_progress_carries_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409, json={"error": "job in progress", "detail": "pump_1 has an active job"}
        )

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.JobInProgressError) as excinfo:
            await transport.discover()
        assert "pump_1" in (excinfo.value.detail or "")
    finally:
        await client.aclose()


async def test_discover_500_maps_failed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "discovery failed", "detail": "boom"})

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.DiscoveryFailedError):
            await transport.discover()
    finally:
        await client.aclose()


async def test_disconnect_404_unknown_device():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "no device on port"})

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.UnknownDeviceError):
            await transport.disconnect(port="COM9")
    finally:
        await client.aclose()


async def test_disconnect_ok_returns_count():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"released": 3})

    transport, client = make_transport(handler)
    try:
        body = await transport.disconnect()
        assert body["released"] == 3
    finally:
        await client.aclose()


async def test_get_devices_403_raises_protocol_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.LabProtocolError):
            await transport.get_devices()
    finally:
        await client.aclose()


async def test_disconnect_400_raises_protocol_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    transport, client = make_transport(handler)
    try:
        with pytest.raises(errors.LabProtocolError):
            await transport.disconnect(port="COM9")
    finally:
        await client.aclose()
