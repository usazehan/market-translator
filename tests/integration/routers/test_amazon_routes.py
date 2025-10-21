# tests/integration/routers/test_amazon_routes.py
from __future__ import annotations

from importlib import reload
from typing import List, Tuple

import pytest


@pytest.fixture(autouse=True)
def env_ready(monkeypatch):
    monkeypatch.setenv("SPAPI_HOST", "https://sandbox.sellingpartnerapi-na.amazon.com")
    monkeypatch.setenv("LWA_CLIENT_ID", "cid")
    monkeypatch.setenv("LWA_CLIENT_SECRET", "secret")
    monkeypatch.setenv("LWA_REFRESH_TOKEN", "rtok")
    monkeypatch.setenv("MARKETPLACE_IDS", "ATVPDKIKX0DER")
    monkeypatch.setenv("SPAPI_SCHEMA_VALIDATE", "1")
    yield


@pytest.fixture
def app_client(env_ready, monkeypatch):
    from fastapi.testclient import TestClient
    import src.app.main as main

    # Stub the LWA token call to avoid network
    import src.app.routers.amazon as amazon_router
    monkeypatch.setattr(amazon_router, "_lwa_access_token", lambda: "ACCESS_TOKEN")

    # Stub the PTD validator to capture arguments
    calls: List[Tuple] = []

    def _fake_validate_attributes_with_ptd(**kwargs):
        calls.append(kwargs)
        # Return one fake schema error to exercise the error path
        return False, ["schema:required:attributes/brand"]

    monkeypatch.setattr(
        amazon_router, "validate_attributes_with_ptd", _fake_validate_attributes_with_ptd
    )

    reload(main)
    client = TestClient(main.app)
    client._calls = calls  # type: ignore[attr-defined]
    return client


def test_amazon_validate_invokes_ptd_and_returns_errors(app_client):
    resp = app_client.post(
        "/amazon/validate",
        json={
            "productType": "PRODUCT",
            "attributes": {"title": [{"value": "Tee"}]},
            "marketplaceId": "ATVPDKIKX0DER",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "schema:required:attributes/brand" in data["errors"]

    # Also assert our stub saw the right args
    calls = getattr(app_client, "_calls")
    assert calls, "validator was not called"
    args = calls[0]
    assert args["product_type"] == "PRODUCT"
    assert args["marketplace_ids"] == ["ATVPDKIKX0DER"]
    assert args["attributes"]["title"][0]["value"] == "Tee"
