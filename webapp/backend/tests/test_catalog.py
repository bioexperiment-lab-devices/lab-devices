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
