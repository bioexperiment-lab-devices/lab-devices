"""SPA static serving: catch-all fallback, asset files, API 404s stay JSON."""

from pathlib import Path

import httpx

from experiment_studio.app import create_app
from experiment_studio.config import Settings


def _make_static(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>experiment studio</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log('studio')")
    return tmp_path


def _client(static_dir: Path | None) -> httpx.AsyncClient:
    app = create_app(Settings(static_dir=static_dir))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://studio")


async def test_root_serves_index(tmp_path: Path) -> None:
    async with _client(_make_static(tmp_path)) as c:
        resp = await c.get("/")
        assert resp.status_code == 200
        assert "experiment studio" in resp.text


async def test_asset_file_served(tmp_path: Path) -> None:
    async with _client(_make_static(tmp_path)) as c:
        resp = await c.get("/assets/app.js")
        assert resp.status_code == 200
        assert "studio" in resp.text


async def test_client_route_falls_back_to_index(tmp_path: Path) -> None:
    async with _client(_make_static(tmp_path)) as c:
        resp = await c.get("/records")
        assert resp.status_code == 200
        assert "experiment studio" in resp.text


async def test_unknown_api_path_stays_json_404(tmp_path: Path) -> None:
    async with _client(_make_static(tmp_path)) as c:
        resp = await c.get("/api/nope")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Not Found"


async def test_traversal_falls_back_to_index(tmp_path: Path) -> None:
    async with _client(_make_static(tmp_path)) as c:
        resp = await c.get("/..%2fpyproject.toml")
        assert resp.status_code == 200
        assert "experiment studio" in resp.text


async def test_without_static_dir_root_is_404(tmp_path: Path) -> None:
    async with _client(None) as c:
        resp = await c.get("/")
        assert resp.status_code == 404
