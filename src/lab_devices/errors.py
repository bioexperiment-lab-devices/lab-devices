"""Exception hierarchy for lab_devices. See spec §6."""

from __future__ import annotations

from typing import Any


class LabDevicesError(Exception):
    """Root of every error raised by this library."""


# --------------------------------------------------------------------------- #
# Discovery layer (lab-bridge / roster)                                        #
# --------------------------------------------------------------------------- #
class DiscoveryError(LabDevicesError):
    """Base for the discovery (LabRegistry) layer."""


class ClientLookupEndpointUnreachable(DiscoveryError):
    """Connection refused / timeout reaching the roster endpoint."""


class ClientLookupEndpointError(DiscoveryError):
    """Roster endpoint returned 5xx or a malformed/non-JSON body."""


class UnknownLabClient(DiscoveryError):
    """Requested lab name is not in the roster."""

    def __init__(self, name: str, available: list[str]) -> None:
        self.name = name
        self.available = available
        super().__init__(f"unknown lab {name!r}; available: {', '.join(available) or '(none)'}")


class LabOffline(DiscoveryError):
    """Lab is in the roster but its tunnel is not reachable (TCP probe failed)."""

    def __init__(self, name: str, host: str, port: int) -> None:
        self.name = name
        self.host = host
        self.port = port
        super().__init__(f"lab {name!r} is offline ({host}:{port} not reachable)")


# --------------------------------------------------------------------------- #
# Device / agent layer                                                         #
# --------------------------------------------------------------------------- #
class LabError(LabDevicesError):
    """Any error from talking to a SerialHop agent."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        self.message = message
        self.code = code
        self.details = details or {}
        self.request_id = request_id
        super().__init__(message)


# -- device-command errors (code / message / details / request_id) -- #
class InvalidRequestError(LabError):
    pass


class UnknownDeviceError(LabError):
    pass


class DeviceUnreachableError(LabError):
    pass


class UnknownCommandError(LabError):
    pass


class InvalidParamsError(LabError):
    pass


class BusyError(LabError):
    @property
    def job_id(self) -> str | None:
        return self.details.get("job_id")


class NotCalibratedError(LabError):
    pass


class NotHomedError(LabError):
    pass


class HardwareError(LabError):
    @property
    def component(self) -> str | None:
        return self.details.get("component")


class InternalDeviceError(LabError):
    pass


# -- job errors -- #
class JobFailedError(LabError):
    """A job reached state 'failed'. `.error` is the raw error object from the job."""

    def __init__(self, error: dict[str, Any], *, request_id: str | None = None) -> None:
        self.error = error or {}
        super().__init__(
            self.error.get("message", "job failed"),
            code=self.error.get("code"),
            details=self.error.get("details"),
            request_id=request_id,
        )


class JobCancelledError(LabError):
    pass


class JobTimeoutError(LabError):
    pass


# -- agent-infra errors ({error, detail} shape; message + detail only) -- #
class DiscoveryInProgressError(LabError):
    pass


class JobInProgressError(LabError):
    def __init__(self, message: str, *, detail: str | None = None) -> None:
        self.detail = detail
        super().__init__(message)


class DiscoveryFailedError(LabError):
    pass


class LabProtocolError(LabError):
    """The response violated the envelope contract (bad shape, id mismatch, oversize body)."""


_COMMAND_ERROR_CLASSES: dict[str, type[LabError]] = {
    "invalid_request": InvalidRequestError,
    "unknown_device": UnknownDeviceError,
    "device_unreachable": DeviceUnreachableError,
    "unknown_command": UnknownCommandError,
    "invalid_params": InvalidParamsError,
    "busy": BusyError,
    "not_calibrated": NotCalibratedError,
    "not_homed": NotHomedError,
    "hardware_error": HardwareError,
    "internal_error": InternalDeviceError,
}


def map_command_error(error: dict[str, Any], request_id: str) -> LabError:
    """Map an envelope error object to a specific exception (unknown code -> base LabError)."""
    code = error.get("code")
    message = error.get("message", "device command failed")
    details = error.get("details")
    cls = _COMMAND_ERROR_CLASSES.get(code or "", LabError)
    return cls(message, code=code, details=details, request_id=request_id)
