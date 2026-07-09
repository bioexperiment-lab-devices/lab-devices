import asyncio

import httpx
import pytest

from lab_devices import errors
from lab_devices.client import LabClient
from lab_devices.discovery import LabInfo, LabRegistry

ROSTER = {
    "khamit_desktop": {"host": "chisel", "port": 8089},
    "natalya_test_user": {"host": "chisel", "port": 8087},
}


def _registry(*, roster=ROSTER, status=200, body=None, boom=None) -> LabRegistry:
    def handler(request: httpx.Request) -> httpx.Response:
        if boom is not None:
            raise boom
        return httpx.Response(status, json=body if body is not None else roster)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://siteapp:8000")
    return LabRegistry(url="http://siteapp:8000/api/clients/", http=http)


async def test_list_labs():
    async with _registry() as reg:
        names = await reg.list_labs()
        assert set(names) == {"khamit_desktop", "natalya_test_user"}


async def test_lookup_known():
    async with _registry() as reg:
        info = await reg.lookup("khamit_desktop")
        assert info == LabInfo(name="khamit_desktop", host="chisel", port=8089)


async def test_lookup_unknown_lists_names():
    async with _registry() as reg:
        with pytest.raises(errors.UnknownLabClient) as excinfo:
            await reg.lookup("ghost")
        assert "khamit_desktop" in excinfo.value.available


async def test_endpoint_unreachable():
    async with _registry(boom=httpx.ConnectError("refused")) as reg:
        with pytest.raises(errors.ClientLookupEndpointUnreachable):
            await reg.list_labs()


async def test_endpoint_5xx():
    async with _registry(status=502, body={"error": "bad gateway"}) as reg:
        with pytest.raises(errors.ClientLookupEndpointError):
            await reg.list_labs()


async def test_connect_online_returns_labclient(monkeypatch):
    async with _registry() as reg:
        # Force the liveness probe to report online without real sockets.
        async def fake_probe(host, port):
            return True

        monkeypatch.setattr(reg, "_probe", fake_probe)
        lab = await reg.connect("khamit_desktop")
        assert isinstance(lab, LabClient)
        assert lab.host == "chisel"
        assert lab.port == 8089
        await lab.aclose()


async def test_connect_offline_raises(monkeypatch):
    async with _registry() as reg:
        async def fake_probe(host, port):
            return False

        monkeypatch.setattr(reg, "_probe", fake_probe)
        with pytest.raises(errors.LabOffline):
            await reg.connect("khamit_desktop")


async def test_lookup_missing_port_raises_endpoint_error():
    roster = {"khamit_desktop": {"host": "chisel"}}
    async with _registry(roster=roster) as reg:
        with pytest.raises(errors.ClientLookupEndpointError):
            await reg.lookup("khamit_desktop")


async def test_lookup_non_numeric_port_raises_endpoint_error():
    roster = {"khamit_desktop": {"host": "chisel", "port": "abc"}}
    async with _registry(roster=roster) as reg:
        with pytest.raises(errors.ClientLookupEndpointError):
            await reg.lookup("khamit_desktop")


async def test_connect_missing_port_raises_endpoint_error():
    roster = {"khamit_desktop": {"host": "chisel"}}
    async with _registry(roster=roster) as reg:
        with pytest.raises(errors.ClientLookupEndpointError):
            await reg.connect("khamit_desktop")


async def test_probe_against_real_server():
    async with _registry() as reg:
        # Handler MUST close the accepted connection: on Python 3.12,
        # Server.wait_closed() blocks until active client connections finish, so a
        # no-op handler that leaves the probe's connection open hangs teardown below.
        server = await asyncio.start_server(lambda r, w: w.close(), "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            assert await reg._probe("127.0.0.1", port) is True
        finally:
            server.close()
            await server.wait_closed()
        # nothing listening now -> offline
        assert await reg._probe("127.0.0.1", port) is False
