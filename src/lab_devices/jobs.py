"""Job handles for long-running commands. See spec §4.3."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Self

from lab_devices import errors
from lab_devices.models import RawModel

if TYPE_CHECKING:
    from lab_devices.devices.base import Device

_TERMINAL = {"succeeded", "failed", "cancelled"}


class Job:
    def __init__(
        self,
        device: "Device",
        job_id: str,
        *,
        result_model: type[RawModel] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self._device = device
        self.job_id = job_id
        self._result_model = result_model
        self.state = "running"
        self.progress: float | None = None
        self.estimated_duration_s: float | None = None
        self.elapsed_s: float | None = None
        self.error: dict[str, Any] | None = None
        self.raw: dict[str, Any] = {}
        if data:
            self._update(data)

    @classmethod
    def from_start_result(
        cls,
        device: "Device",
        result: Any,
        *,
        result_model: type[RawModel] | None = None,
    ) -> Self:
        job_obj = (result or {}).get("job") if isinstance(result, dict) else None
        if not isinstance(job_obj, dict) or "job_id" not in job_obj:
            raise errors.LabProtocolError("command did not return a job object")
        return cls(device, job_obj["job_id"], result_model=result_model, data=job_obj)

    def _update(self, data: dict[str, Any]) -> None:
        self.raw = data
        self.state = data.get("state", self.state)
        self.progress = data.get("progress", self.progress)
        self.estimated_duration_s = data.get("estimated_duration_s", self.estimated_duration_s)
        self.elapsed_s = data.get("elapsed_s", self.elapsed_s)
        self.error = data.get("error", self.error)

    async def refresh(self) -> Self:
        data = await self._device._transport.command(
            self._device.id, "get_job", {"job_id": self.job_id}
        )
        if isinstance(data, dict):
            self._update(data)
        return self

    async def result(
        self,
        *,
        poll_interval: float = 0.25,
        max_interval: float = 2.0,
        timeout: float | None = None,
    ) -> Any:
        interval = poll_interval
        try:
            async with asyncio.timeout(timeout):
                while self.state not in _TERMINAL:
                    await self.refresh()
                    if self.state in _TERMINAL:
                        break
                    await asyncio.sleep(interval)
                    interval = min(interval * 2 or max_interval, max_interval)
        except TimeoutError as exc:
            raise errors.JobTimeoutError(
                f"job {self.job_id} did not finish within {timeout}s"
            ) from exc

        if self.state == "succeeded":
            payload = self.raw.get("result")
            if self._result_model is not None:
                return self._result_model.from_raw(payload)
            return payload
        if self.state == "failed":
            raise errors.JobFailedError(self.error or {})
        raise errors.JobCancelledError(f"job {self.job_id} was cancelled")

    async def cancel(self) -> Any:
        return await self._device.stop()


class PumpJob(Job):
    async def pause(self) -> Any:
        # `_device` is typed as the base `Device`, but a PumpJob is only ever
        # constructed for a Pump, which does define `pause`/`resume`.
        return await self._device.pause()  # type: ignore[attr-defined]

    async def resume(self) -> Any:
        return await self._device.resume()  # type: ignore[attr-defined]
