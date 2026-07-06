"""Base device: universal commands shared by every device type. See spec §4.2."""

from __future__ import annotations

from typing import Any, ClassVar

from lab_devices.jobs import Job
from lab_devices.models import Identify, PingResult, RawModel
from lab_devices.transport import Transport


class Device:
    STATUS_MODEL: ClassVar[type[RawModel] | None] = None
    CAPABILITIES_MODEL: ClassVar[type[RawModel] | None] = None

    def __init__(self, transport: Transport, device_id: str) -> None:
        self._transport = transport
        self.id = device_id
        self.type = device_id.rsplit("_", 1)[0]

    async def ping(self) -> PingResult:
        return PingResult.from_raw(await self._transport.command(self.id, "ping"))

    async def status(self) -> Any:
        result = await self._transport.command(self.id, "status")
        if self.STATUS_MODEL is not None and isinstance(result, dict):
            return self.STATUS_MODEL.from_raw(result)
        return result

    async def identify(self) -> Identify:
        result = await self._transport.command(self.id, "identify")
        identify = Identify.from_raw(result if isinstance(result, dict) else {})
        if self.CAPABILITIES_MODEL is not None and isinstance(result, dict):
            identify.capabilities = self.CAPABILITIES_MODEL.from_raw(result.get("capabilities"))
        return identify

    async def stop(self) -> Any:
        return await self._transport.command(self.id, "stop")

    async def get_job(self, job_id: str) -> Job:
        data = await self._transport.command(self.id, "get_job", {"job_id": job_id})
        return Job(self, job_id, data=data if isinstance(data, dict) else None)

    async def command(self, cmd: str, params: dict[str, Any] | None = None) -> Any:
        """Raw escape hatch for any command not wrapped by a typed method."""
        return await self._transport.command(self.id, cmd, params)

    async def _start_job(
        self,
        cmd: str,
        params: dict[str, Any] | None = None,
        *,
        result_model: type[RawModel] | None = None,
        job_cls: type[Job] = Job,
    ) -> Job:
        result = await self._transport.command(self.id, cmd, params)
        return job_cls.from_start_result(self, result, result_model=result_model)
