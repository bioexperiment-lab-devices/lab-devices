"""LabClient — core entry point for one lab. See spec §4.1."""

from __future__ import annotations

from typing import Any, Self

import httpx

from lab_devices.devices.base import Device
from lab_devices.devices.densitometer import Densitometer
from lab_devices.devices.pump import Pump
from lab_devices.devices.valve import Valve
from lab_devices.models import AgentInfo, DeviceInfo
from lab_devices.transport import Transport

_PREFIX_TO_CLASS: dict[str, type[Device]] = {
    "pump": Pump,
    "valve": Valve,
    "densitometer": Densitometer,
}


class LabClient:
    def __init__(
        self,
        host: str,
        port: int,
        *,
        request_timeout: float = 10.0,
        discover_timeout: float = 30.0,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=f"http://{host}:{port}", timeout=request_timeout
        )
        self._transport = Transport(self._http, discover_timeout=discover_timeout)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # ---- device handles (lazy) ----
    def pump(self, n: int) -> Pump:
        return Pump(self._transport, f"pump_{n}")

    def valve(self, n: int) -> Valve:
        return Valve(self._transport, f"valve_{n}")

    def densitometer(self, n: int) -> Densitometer:
        return Densitometer(self._transport, f"densitometer_{n}")

    def device(self, device_id: str) -> Device:
        prefix = device_id.rsplit("_", 1)[0]
        cls = _PREFIX_TO_CLASS.get(prefix)
        if cls is None:
            raise ValueError(f"unrecognized device id prefix: {device_id!r}")
        return cls(self._transport, device_id)

    # ---- enumeration & lifecycle ----
    async def list_devices(self) -> list[DeviceInfo]:
        body = await self._transport.get_devices()
        return [DeviceInfo.from_raw(d) for d in body.get("devices", [])]

    async def rediscover(self) -> list[DeviceInfo]:
        body = await self._transport.discover()
        return [DeviceInfo.from_raw(d) for d in body.get("devices", [])]

    async def disconnect(self, port: str | None = None) -> int:
        body = await self._transport.disconnect(port)
        return int(body.get("released", 0))

    async def agent_info(self) -> AgentInfo:
        return AgentInfo.from_raw(await self._transport.agent_info())
