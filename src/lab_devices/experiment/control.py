"""Operator control plane: introspection + guarded recovery around a run. See design 5 §9."""

from __future__ import annotations

from typing import Any

from lab_devices.client import LabClient
from lab_devices.experiment.errors import DeviceBusyError
from lab_devices.experiment.run import ExperimentRun
from lab_devices.models import AgentInfo, DeviceInfo, PingResult


class Console:
    """Out-of-band operator surface (parent §3.2, design 5 §9). Never a block."""

    def __init__(self, client: LabClient, run: ExperimentRun | None = None) -> None:
        self._client = client
        self._run = run

    # ---- introspection (always safe, read-only) ----
    async def list_devices(self) -> list[DeviceInfo]:
        return await self._client.list_devices()

    async def agent_info(self) -> AgentInfo:
        return await self._client.agent_info()

    async def device_status(self, device_id: str) -> Any:
        device = self._client.device(device_id)
        if self._run is not None:
            async with self._run.wire_lock(device_id):
                return await device.status()
        return await device.status()

    async def device_ping(self, device_id: str) -> PingResult:
        device = self._client.device(device_id)
        if self._run is not None:
            async with self._run.wire_lock(device_id):
                return await device.ping()
        return await device.ping()

    # ---- recovery (mutating, guarded: idle-only, design 5 §9) ----
    async def rediscover(self) -> list[DeviceInfo]:
        self._refuse_if_any_busy()
        return await self._client.rediscover()

    async def disconnect(self, device_id: str | None = None) -> int:
        if device_id is None:
            self._refuse_if_any_busy()
            return await self._client.disconnect()
        if self._run is not None and self._run.is_device_busy(device_id):
            raise DeviceBusyError(
                f"device {device_id!r} is busy; abort the run or wait before disconnecting"
            )
        return await self._client.disconnect(await self._port_of(device_id))

    def _refuse_if_any_busy(self) -> None:
        if self._run is None:
            return
        busy = self._run.busy_devices()
        if busy:
            raise DeviceBusyError(
                f"cannot recover while devices are busy: {sorted(busy)}; abort the run first"
            )

    async def _port_of(self, device_id: str) -> str | None:
        for info in await self._client.list_devices():
            if info.id == device_id:
                return info.port
        raise ValueError(f"unknown device id: {device_id!r}")
