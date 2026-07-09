"""Async library to discover and manage lab devices (pump, valve, densitometer).

Quick start:

    from lab_devices import LabClient

    async with LabClient("chisel", 8089) as lab:
        job = await lab.pump(1).dispense(volume_ml=10, speed_ml_min=3.0)
        result = await job.result()

Server-only discovery (inside labnet):

    from lab_devices.discovery import LabRegistry

    async with LabRegistry() as reg:
        lab = await reg.connect("khamit_desktop")
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _version

from lab_devices.client import LabClient
from lab_devices.devices import Densitometer, Device, Pump, Valve
from lab_devices.errors import (
    BusyError,
    ClientLookupEndpointError,
    ClientLookupEndpointUnreachable,
    DeviceUnreachableError,
    DiscoveryError,
    DiscoveryFailedError,
    DiscoveryInProgressError,
    HardwareError,
    InternalDeviceError,
    InvalidParamsError,
    InvalidRequestError,
    JobCancelledError,
    JobFailedError,
    JobInProgressError,
    JobTimeoutError,
    LabDevicesError,
    LabError,
    LabOffline,
    LabProtocolError,
    NotCalibratedError,
    NotHomedError,
    UnknownCommandError,
    UnknownDeviceError,
    UnknownLabClient,
)
from lab_devices.jobs import Job, PumpJob
from lab_devices.models import (
    AgentInfo,
    Calibration,
    CalibrationRunResult,
    DensitometerCapabilities,
    DensitometerStatus,
    DeviceInfo,
    DispenseResult,
    Identify,
    MeasureResult,
    PingResult,
    PumpCapabilities,
    PumpStatus,
    Range,
    RawModel,
    ReadRawResult,
    Reading,
    ReadingsResult,
    Thermostat,
    ThermostatState,
    ValveCapabilities,
    ValveConfig,
    ValveMoveResult,
    ValveStatus,
)

try:
    __version__ = _version("bioexperiment-lab-devices")
except PackageNotFoundError:  # pragma: no cover - running from an uninstalled source tree
    __version__ = "0.0.0.dev0"

# NOTE: kept as a plain sorted literal list (rather than `sorted([...])`) so ruff's
# re-export detection (F401) recognizes every name below as intentionally exported.
__all__ = [
    "AgentInfo",
    "BusyError",
    "Calibration",
    "CalibrationRunResult",
    "ClientLookupEndpointError",
    "ClientLookupEndpointUnreachable",
    "Densitometer",
    "DensitometerCapabilities",
    "DensitometerStatus",
    "Device",
    "DeviceInfo",
    "DeviceUnreachableError",
    "DiscoveryError",
    "DiscoveryFailedError",
    "DiscoveryInProgressError",
    "DispenseResult",
    "HardwareError",
    "Identify",
    "InternalDeviceError",
    "InvalidParamsError",
    "InvalidRequestError",
    "Job",
    "JobCancelledError",
    "JobFailedError",
    "JobInProgressError",
    "JobTimeoutError",
    "LabClient",
    "LabDevicesError",
    "LabError",
    "LabOffline",
    "LabProtocolError",
    "MeasureResult",
    "NotCalibratedError",
    "NotHomedError",
    "PingResult",
    "Pump",
    "PumpCapabilities",
    "PumpJob",
    "PumpStatus",
    "Range",
    "RawModel",
    "ReadRawResult",
    "Reading",
    "ReadingsResult",
    "Thermostat",
    "ThermostatState",
    "UnknownCommandError",
    "UnknownDeviceError",
    "UnknownLabClient",
    "Valve",
    "ValveCapabilities",
    "ValveConfig",
    "ValveMoveResult",
    "ValveStatus",
]
