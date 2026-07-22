"""Catalog endpoint: thin serialization of the library accessors."""

import httpx


async def test_catalog_shape(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/catalog")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"device_types", "expression"}
    dispense = body["device_types"]["pump"]["dispense"]
    assert dispense["kind"] == "command"
    assert dispense["params"][0] == {"name": "volume_ml", "type": "number", "required": True}
    assert body["device_types"]["densitometer"]["measure"]["result_field"] == "absorbance"
    assert body["expression"]["functions"] == ["count", "last", "max", "mean", "min"]


async def test_catalog_exposes_read_temperature_and_param_hints(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/catalog")).json()
    dens = body["device_types"]["densitometer"]
    assert dens["read_temperature"]["kind"] == "measure"
    assert dens["read_temperature"]["result_field"] == "temperature_c"
    direction = {p["name"]: p for p in body["device_types"]["pump"]["dispense"]["params"]}
    assert direction["direction"]["default"] == "forward"
    rotation = {p["name"]: p for p in body["device_types"]["valve"]["set_position"]["params"]}
    assert rotation["rotation"]["on_omit"] == "default"
