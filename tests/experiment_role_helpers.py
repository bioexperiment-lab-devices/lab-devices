"""Test-only role synthesis. Engine tests name devices by the core id convention; v2
requires a declaration for each. This derives one so the suites keep loading -- it is
NOT the engine's rule, which reads workflow.roles[name].type and nothing else."""

from typing import Any

from lab_devices.experiment.registry import DEVICE_TYPES


def auto_roles(doc: Any) -> dict[str, dict[str, str]]:
    """Declare a role for every literal `device` name in `doc`, typed by its id suffix and
    bound to the identically-named physical device. Names whose suffix is not a known device
    type are skipped, so negative tests that target an unknown type still reach the
    diagnostic they were written for."""
    found: dict[str, dict[str, str]] = {}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            device = node.get("device")
            if isinstance(device, str) and "{" not in device:
                dtype = device.rsplit("_", 1)[0]
                if dtype in DEVICE_TYPES:
                    found[device] = {"type": dtype, "device": device}
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(doc)
    return found
