"""LabRegistry — server-only lab discovery via the internal lab-bridge roster.

Runs inside labnet. Hits the unauthenticated internal endpoint
`GET http://siteapp:8000/api/clients/` -> {name: {host, port}}. No token. See spec §5."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Self

import httpx

from lab_devices import errors
from lab_devices.client import LabClient

_DEFAULT_URL = "http://siteapp:8000/api/clients/"


@dataclass(frozen=True)
class LabInfo:
    name: str
    host: str
    port: int


class LabRegistry:
    def __init__(
        self,
        *,
        url: str | None = None,
        chisel_host: str | None = None,
        probe_timeout: float = 0.3,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.url = url or os.environ.get("LAB_DEVICES_DISCOVERY_URL") or _DEFAULT_URL
        self._chisel_host = chisel_host
        self._probe_timeout = probe_timeout
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _fetch_roster(self) -> dict[str, dict[str, Any]]:
        try:
            response = await self._http.get(self.url)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
            raise errors.ClientLookupEndpointUnreachable(str(exc)) from exc
        except httpx.TransportError as exc:
            raise errors.ClientLookupEndpointUnreachable(str(exc)) from exc
        if response.status_code >= 500:
            raise errors.ClientLookupEndpointError(f"roster endpoint HTTP {response.status_code}")
        try:
            body = response.json()
        except (ValueError, httpx.DecodingError) as exc:
            raise errors.ClientLookupEndpointError("roster body is not JSON") from exc
        if not isinstance(body, dict):
            raise errors.ClientLookupEndpointError("roster body is not an object")
        return body

    async def list_labs(self) -> list[str]:
        return sorted((await self._fetch_roster()).keys())

    async def lookup(self, name: str) -> LabInfo:
        roster = await self._fetch_roster()
        entry = roster.get(name)
        if entry is None:
            raise errors.UnknownLabClient(name, available=sorted(roster.keys()))
        if not isinstance(entry, dict):
            raise errors.ClientLookupEndpointError(
                f"malformed roster entry for {name!r}: not an object"
            )
        try:
            port = int(entry["port"])
        except (KeyError, ValueError, TypeError) as exc:
            raise errors.ClientLookupEndpointError(
                f"malformed roster entry for {name!r}: invalid or missing port"
            ) from exc
        host = self._chisel_host or entry.get("host", "chisel")
        return LabInfo(name=name, host=host, port=port)

    async def is_online(self, name: str) -> bool:
        info = await self.lookup(name)
        return await self._probe(info.host, info.port)

    async def connect(
        self, name: str, *, require_online: bool = True, **client_kwargs: Any
    ) -> LabClient:
        info = await self.lookup(name)
        if require_online and not await self._probe(info.host, info.port):
            raise errors.LabOffline(name, info.host, info.port)
        return LabClient(info.host, info.port, **client_kwargs)

    async def _probe(self, host: str, port: int) -> bool:
        try:
            async with asyncio.timeout(self._probe_timeout):
                reader, writer = await asyncio.open_connection(host, port)
        except (OSError, TimeoutError):
            return False
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        return True
