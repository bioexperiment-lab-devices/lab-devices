"""TRANSITIONAL id->type derivation (design 2026-07-20 §5.2). DELETE THIS FILE.

`registry.device_type` is gone: a device type now comes from `workflow.roles[name].type`.
The validator, executor, finalizer, and loader cannot read a declaration until roles are
threaded through them, so they route through this one named function in the meantime.
`grep -rn legacy_device_type src` is the complete list of sites the role-threading task
must convert; when it returns nothing, delete this module.
"""

from __future__ import annotations


def legacy_device_type(device_id: str) -> str:
    """Mirror the core's Device.type derivation (client.py:62, devices/base.py:19)."""
    return device_id.rsplit("_", 1)[0]
