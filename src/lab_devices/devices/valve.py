"""Distribution valve. See spec §3.7."""

from __future__ import annotations

from typing import Any, ClassVar

from lab_devices.devices.base import Device
from lab_devices.jobs import Job
from lab_devices.models.common import RawModel
from lab_devices.models.valve import ValveCapabilities, ValveMoveResult, ValveStatus


class Valve(Device):
    STATUS_MODEL: ClassVar[type[RawModel] | None] = ValveStatus
    CAPABILITIES_MODEL: ClassVar[type[RawModel] | None] = ValveCapabilities

    async def home(self, *, position: int) -> Any:
        return await self.command("home", {"position": position})

    async def set_position(self, *, position: int, rotation: str | None = None) -> Job:
        params: dict[str, Any] = {"position": position}
        if rotation is not None:
            params["rotation"] = rotation
        return await self._start_job("set_position", params, result_model=ValveMoveResult)

    async def configure(
        self, *, default_rotation: str | None = None, hold_torque: bool | None = None
    ) -> Any:
        params: dict[str, Any] = {}
        if default_rotation is not None:
            params["default_rotation"] = default_rotation
        if hold_torque is not None:
            params["hold_torque"] = hold_torque
        return await self.command("configure", params)
