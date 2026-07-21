"""Roster + per-lab device introspection over LabRegistry/LabClient. See webapp design §6."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from lab_devices.client import LabClient
from lab_devices.discovery import LabInfo, LabRegistry
from lab_devices.models.common import DeviceInfo

ClientFactory = Callable[[LabInfo], LabClient]
Probe = Callable[[str], Awaitable[bool]]


def device_json(device: DeviceInfo) -> dict[str, Any]:
    identify = device.identify
    return {
        "id": device.id,
        "type": device.type,
        "port": device.port,
        "connected": device.connected,
        "model": identify.model if identify is not None else None,
        "firmware": identify.firmware_version if identify is not None else None,
    }


def _default_client_factory(info: LabInfo) -> LabClient:
    return LabClient(info.host, info.port)


class LabsService:
    """Stateless per-request lab access; one LabClient per call, always closed."""

    def __init__(
        self,
        registry: LabRegistry,
        *,
        client_factory: ClientFactory | None = None,
        probe: Probe | None = None,
    ) -> None:
        self._registry = registry
        self._client_factory = client_factory or _default_client_factory
        self._probe = probe or registry.is_online

    async def list_labs(self) -> list[dict[str, Any]]:
        names = await self._registry.list_labs()
        online = await asyncio.gather(*(self._probe(name) for name in names))
        out: list[dict[str, Any]] = []
        for name, up in zip(names, online):
            info = await self._registry.lookup(name)
            out.append({"name": name, "host": info.host, "port": info.port, "online": up})
        return out

    async def devices(self, lab: str) -> list[dict[str, Any]]:
        info = await self._registry.lookup(lab)
        async with self._client_factory(info) as client:
            return [device_json(d) for d in await client.list_devices()]

    async def discover(self, lab: str) -> list[dict[str, Any]]:
        info = await self._registry.lookup(lab)
        async with self._client_factory(info) as client:
            return [device_json(d) for d in await client.rediscover()]

    async def command(
        self, lab: str, device_id: str, cmd: str, params: dict[str, Any] | None
    ) -> Any:
        """Run a single device command and return its raw result (design §6.1)."""
        info = await self._registry.lookup(lab)
        async with self._client_factory(info) as client:
            return await client.device(device_id).command(cmd, params)

    async def get_job(self, lab: str, device_id: str, job_id: str) -> Any:
        """Fetch a job's raw status/result by id (design §6.2)."""
        info = await self._registry.lookup(lab)
        async with self._client_factory(info) as client:
            return await client.device(device_id).command("get_job", {"job_id": job_id})

    async def aclose(self) -> None:
        await self._registry.aclose()
