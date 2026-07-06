"""Sole owner of HTTP + JSON. Devices call semantic methods here; this module maps
the envelope and infra responses to the exception hierarchy. See spec §4.4, §6."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from lab_devices import errors

_MAX_BODY_BYTES = 32 * 1024


class Transport:
    def __init__(self, client: httpx.AsyncClient, *, discover_timeout: float = 30.0) -> None:
        self._client = client
        self._discover_timeout = discover_timeout

    async def command(
        self,
        device_id: str,
        cmd: str,
        params: dict[str, Any] | None = None,
        *,
        request_id: str | None = None,
        timeout: float | None = None,
    ) -> Any:
        req_id = request_id or str(uuid.uuid4())
        envelope: dict[str, Any] = {"id": req_id, "cmd": cmd}
        if params is not None:
            envelope["params"] = params

        payload = json.dumps(envelope).encode()
        if len(payload) > _MAX_BODY_BYTES:
            raise errors.LabProtocolError(
                f"request body {len(payload)} bytes exceeds 32 KiB cap", request_id=req_id
            )

        kwargs: dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        response = await self._client.post(
            f"/api/v1/devices/{device_id}/command",
            content=payload,
            headers={"Content-Type": "application/json"},
            **kwargs,
        )
        return self._parse_envelope(response, req_id)

    @staticmethod
    def _parse_envelope(response: httpx.Response, req_id: str) -> Any:
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise errors.LabProtocolError(
                f"non-JSON response (HTTP {response.status_code})", request_id=req_id
            ) from exc
        if not isinstance(body, dict) or "status" not in body:
            raise errors.LabProtocolError("malformed envelope", request_id=req_id)

        echoed = body.get("id", "")
        if echoed not in (req_id, ""):
            raise errors.LabProtocolError(
                f"correlation id mismatch: sent {req_id!r}, got {echoed!r}", request_id=req_id
            )

        if body["status"] == "ok":
            return body.get("result")
        if body["status"] == "error":
            raise errors.map_command_error(body.get("error") or {}, request_id=req_id)
        raise errors.LabProtocolError(f"unknown status {body['status']!r}", request_id=req_id)
