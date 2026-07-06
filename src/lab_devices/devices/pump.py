"""Peristaltic pump. See spec §3.6."""

from __future__ import annotations

from typing import Any, ClassVar

from lab_devices.devices.base import Device
from lab_devices.jobs import Job, PumpJob
from lab_devices.models.common import RawModel
from lab_devices.models.pump import (
    Calibration,
    CalibrationRunResult,
    DispenseResult,
    PumpCapabilities,
    PumpStatus,
)


class Pump(Device):
    STATUS_MODEL: ClassVar[type[RawModel] | None] = PumpStatus
    CAPABILITIES_MODEL: ClassVar[type[RawModel] | None] = PumpCapabilities

    async def rotate(self, *, direction: str, speed_ml_min: float) -> Any:
        return await self.command(
            "rotate", {"direction": direction, "speed_ml_min": speed_ml_min}
        )

    async def rotate_raw(self, *, direction: str, speed_pct: float) -> Any:
        return await self.command("rotate_raw", {"direction": direction, "speed_pct": speed_pct})

    async def dispense(
        self,
        *,
        volume_ml: float,
        speed_ml_min: float | None = None,
        direction: str = "forward",
        drop_suckback_ml: float | None = None,
        speed_profile: dict[str, Any] | None = None,
    ) -> PumpJob:
        params: dict[str, Any] = {"direction": direction, "volume_ml": volume_ml}
        if speed_ml_min is not None:
            params["speed_ml_min"] = speed_ml_min
        if drop_suckback_ml is not None:
            params["drop_suckback_ml"] = drop_suckback_ml
        if speed_profile is not None:
            params["speed_profile"] = speed_profile
        job = await self._start_job(
            "dispense", params, result_model=DispenseResult, job_cls=PumpJob
        )
        return job  # type: ignore[return-value]

    async def pause(self) -> Any:
        return await self.command("pause")

    async def resume(self) -> Any:
        return await self.command("resume")

    async def start_calibration(self, *, speed_pct: float | None = None) -> Job:
        params = {"speed_pct": speed_pct} if speed_pct is not None else None
        return await self._start_job(
            "start_calibration", params, result_model=CalibrationRunResult
        )

    async def set_calibration(
        self,
        *,
        job_id: str | None = None,
        measured_volume_ml: float | None = None,
        ml_per_step: float | None = None,
    ) -> Any:
        params: dict[str, Any] = {}
        if job_id is not None:
            params["job_id"] = job_id
        if measured_volume_ml is not None:
            params["measured_volume_ml"] = measured_volume_ml
        if ml_per_step is not None:
            params["ml_per_step"] = ml_per_step
        return await self.command("set_calibration", params)

    async def get_calibration(self) -> Calibration:
        return Calibration.from_raw(await self.command("get_calibration"))
