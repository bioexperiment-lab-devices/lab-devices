"""Densitometer. See spec §3.8."""

from __future__ import annotations

from typing import Any, ClassVar

from lab_devices.devices.base import Device
from lab_devices.jobs import Job
from lab_devices.models.common import RawModel
from lab_devices.models.densitometer import (
    DensitometerCapabilities,
    DensitometerStatus,
    MeasureResult,
    ReadingsResult,
    ReadRawResult,
)


class Densitometer(Device):
    STATUS_MODEL: ClassVar[type[RawModel] | None] = DensitometerStatus
    CAPABILITIES_MODEL: ClassVar[type[RawModel] | None] = DensitometerCapabilities

    async def measure_blank(self) -> Job:
        return await self._start_job("measure_blank")

    async def measure(self, *, include_raw: bool = False) -> Job:
        params = {"include_raw": include_raw} if include_raw else None
        return await self._start_job("measure", params, result_model=MeasureResult)

    async def start_monitoring(self, *, interval_s: float | None = None) -> Any:
        params = {"interval_s": interval_s} if interval_s is not None else None
        return await self.command("start_monitoring", params)

    async def get_readings(
        self, *, since_seq: int | None = None, limit: int | None = None
    ) -> ReadingsResult:
        params: dict[str, Any] = {}
        if since_seq is not None:
            params["since_seq"] = since_seq
        if limit is not None:
            params["limit"] = limit
        return ReadingsResult.from_raw(await self.command("get_readings", params or None))

    async def stop_monitoring(self) -> Any:
        return await self.command("stop_monitoring")

    async def set_thermostat(self, *, enabled: bool, target_c: float | None = None) -> Any:
        params: dict[str, Any] = {"enabled": enabled}
        if target_c is not None:
            params["target_c"] = target_c
        return await self.command("set_thermostat", params)

    async def set_tube_correction(self, *, factor: float) -> Any:
        return await self.command("set_tube_correction", {"factor": factor})

    async def calibrate_tube(self, *, reference_absorbance: float) -> Any:
        return await self.command("calibrate_tube", {"reference_absorbance": reference_absorbance})

    async def set_led(self, *, level: int) -> Any:
        return await self.command("set_led", {"level": level})

    async def read_raw(self, *, level: int | None = None) -> Job:
        params = {"level": level} if level is not None else None
        return await self._start_job("read_raw", params, result_model=ReadRawResult)
