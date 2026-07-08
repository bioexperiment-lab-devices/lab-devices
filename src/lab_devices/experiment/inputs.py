"""Operator-input provider protocol, unattended default, fail-safe validation.
See design 4-exec §8."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from lab_devices.experiment.errors import EvaluationError
from lab_devices.experiment.state import BindingValue


@dataclass(frozen=True)
class InputRequest:
    """Everything a provider needs to prompt the operator for one binding."""

    name: str
    type: str
    prompt: str | None
    min: float | None
    max: float | None
    choices: list[str] | None
    block_id: str


class OperatorInputProvider(Protocol):
    async def request(self, request: InputRequest) -> BindingValue: ...


class UnattendedInputProvider:
    """Default provider: no operator wired; any request fails the block (fail-safe)."""

    async def request(self, request: InputRequest) -> BindingValue:
        raise EvaluationError(
            f"operator input {request.name!r} requested but no input provider is configured"
        )


def validate_input_value(request: InputRequest, value: BindingValue) -> BindingValue:
    """Executor-side check of a provider's value; providers own any re-prompt UX."""
    kind = request.type
    if kind == "bool":
        if not isinstance(value, bool):
            raise EvaluationError(f"input {request.name!r} requires a bool, got {value!r}")
        return value
    if kind == "enum":
        if not isinstance(value, str):
            raise EvaluationError(
                f"input {request.name!r} requires a string choice, got {value!r}"
            )
        if request.choices is not None and value not in request.choices:
            raise EvaluationError(
                f"input {request.name!r} must be one of {request.choices!r}, got {value!r}"
            )
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            raise EvaluationError(f"input {request.name!r} requires an int, got {value!r}")
        number = float(value)
    elif kind == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EvaluationError(f"input {request.name!r} requires a number, got {value!r}")
        number = float(value)
    else:
        raise EvaluationError(f"input {request.name!r} has unsupported type {kind!r}")
    if request.min is not None and number < request.min:
        raise EvaluationError(f"input {request.name!r} below min {request.min}: {value!r}")
    if request.max is not None and number > request.max:
        raise EvaluationError(f"input {request.name!r} above max {request.max}: {value!r}")
    return value
