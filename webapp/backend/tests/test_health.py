"""Health endpoint contract."""

from importlib.metadata import version

import httpx


async def test_health_reports_ok_and_versions(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["library"]
    assert body["studio"] == version("experiment-studio")
