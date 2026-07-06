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

    async def get_devices(self) -> dict[str, Any]:
        response = await self._client.get("/api/v1/devices")
        return self._infra_body(response)

    async def discover(self) -> dict[str, Any]:
        response = await self._client.post("/api/v1/discover", timeout=self._discover_timeout)
        if response.status_code == 409:
            body = self._safe_json(response)
            if body.get("error") == "job in progress":
                raise errors.JobInProgressError(
                    body.get("error", "job in progress"), detail=body.get("detail")
                )
            raise errors.DiscoveryInProgressError(body.get("error", "discovery in progress"))
        if response.status_code >= 500:
            body = self._safe_json(response)
            raise errors.DiscoveryFailedError(
                body.get("detail") or body.get("error", "discovery failed")
            )
        return self._infra_body(response)

    async def disconnect(self, port: str | None = None) -> dict[str, Any]:
        params = {"port": port} if port is not None else None
        response = await self._client.post("/devices/disconnect", params=params)
        if response.status_code == 404:
            body = self._safe_json(response)
            raise errors.UnknownDeviceError(
                body.get("error", "no device on that port"),
                code="unknown_device",
                details={"port": port},
            )
        return self._infra_body(response)

    async def agent_info(self) -> dict[str, Any]:
        response = await self._client.get("/agent/info")
        return self._infra_body(response)

    @staticmethod
    def _safe_json(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except (json.JSONDecodeError, ValueError):
            return {}
        return body if isinstance(body, dict) else {}

    def _infra_body(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code >= 400:
            raise errors.LabProtocolError(f"unexpected HTTP {response.status_code}")
        body = self._safe_json(response)
        if not body:
            raise errors.LabProtocolError(f"malformed infra body (HTTP {response.status_code})")
        return body

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
            error_obj = body.get("error") or {}
            if not isinstance(error_obj, dict):
                raise errors.LabProtocolError(
                    "malformed envelope: error is not an object", request_id=req_id
                )
            raise errors.map_command_error(error_obj, request_id=req_id)
        raise errors.LabProtocolError(f"unknown status {body['status']!r}", request_id=req_id)
