from __future__ import annotations

import json as pyjson
import types
from typing import Any, Dict, List, Tuple

import pytest

# We'll import modules inside fixtures/functions after env is set.


# ---------- utilities: a very small httpx.Client stub that records calls ----------

class _Resp:
    def __init__(self, status_code: int = 200, payload: Dict[str, Any] | None = None):
        self.status_code = status_code
        self._payload = payload or {}
    def json(self):
        return self._payload


class _HttpxClientStub:
    """
    Records calls and returns canned responses keyed by (METHOD, URL).
    Use mapping like:
      {
        ("PUT", "https://api.sandbox.ebay.com/sell/inventory/v1/inventory_item/SKU"): _Resp(200),
        ("GET", "https://api.sandbox.ebay.com/sell/inventory/v1/offer?sku=SKU"): _Resp(200, {"offers":[]}),
        ...
      }
    """
    calls: List[Tuple[str, str, str]]  # (method, url, body)

    def __init__(self, mapping: Dict[Tuple[str, str], _Resp], timeout: float | int | None = None):
        self._mapping = mapping
        self.calls = []

    # context manager
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False

    def _make_key(self, method: str, url: str, params: Dict[str, Any] | None) -> Tuple[str, str]:
        if params:
            # The code only adds very simple query params; build the same strings:
            if "category_id" in params:
                url = f"{url}?category_id={params['category_id']}"
            if "marketplace_id" in params:
                url = f"{url}?marketplace_id={params['marketplace_id']}"
            if "sku" in params:
                url = f"{url}?sku={params['sku']}"
        return (method.upper(), url)

    def get(self, url, headers=None, params=None):
        key = self._make_key("GET", url, params)
        self.calls.append(("GET", key[1], ""))  # body empty for GET
        return self._mapping.get(key, _Resp(200, {}))

    def post(self, url, headers=None, content=None, json_body=None):
        body = content.decode() if isinstance(content, (bytes, bytearray)) else (json_body if json_body is not None else "")
        key = self._make_key("POST", url, None)
        self.calls.append(("POST", key[1], body if isinstance(body, str) else pyjson.dumps(body)))
        return self._mapping.get(key, _Resp(200, {}))

    def put(self, url, headers=None, content=None, json_body=None):
        body = content.decode() if isinstance(content, (bytes, bytearray)) else (json_body if json_body is not None else "")
        key = self._make_key("PUT", url, None)
        self.calls.append(("PUT", key[1], body if isinstance(body, str) else pyjson.dumps(body)))
        return self._mapping.get(key, _Resp(200, {}))


# ---------- fixtures ----------

@pytest.fixture
def env_ready(monkeypatch):
    # Set env so router/client creation is happy
    monkeypatch.setenv("EBAY_BASE_URL", "https://api.sandbox.ebay.com")
    monkeypatch.setenv("EBAY_MARKETPLACE_ID", "EBAY_US")
    monkeypatch.setenv("EBAY_CLIENT_ID", "cid")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    monkeypatch.setenv("EBAY_REFRESH_TOKEN", "rtok")
    yield


@pytest.fixture
def app_client(env_ready, monkeypatch):
    # Import after env is set
    from fastapi.testclient import TestClient
    from importlib import reload
    import src.app.main as main

    # Reload to ensure routers bind with fresh env each test
    reload(main)
    client = TestClient(main.app)
    yield client


# ---------- tests ----------

def test_validate_missing_required_aspects(monkeypatch, app_client):
    """
    /ebay/validate should include aspects:missing:* for category-required aspects.
    """
    # Patch ebay module symbols used by router
    import channels.ebay as ebay

    # Avoid network for tokens
    monkeypatch.setattr(ebay, "_app_token", lambda scope="https://api.ebay.com/oauth/api_scope": "APP_TOK")
    monkeypatch.setattr(ebay, "_user_token", lambda scopes=None: "USER_TOK")

    # Force required aspects for the category
    monkeypatch.setattr(ebay, "_required_aspects", lambda cat: ["Brand", "Size"])

    # Stub httpx.Client used inside ebay._required_aspects() calls (not needed here since we forced it),
    # but set anyway to be safe if the code path changes.
    stub = _HttpxClientStub(mapping={})
    monkeypatch.setattr(ebay, "httpx", types.SimpleNamespace(Client=lambda timeout=None: stub))

    # Now call the API
    resp = app_client.post(
        "/ebay/validate",
        json={
            "title": "Premium Cotton Tee",
            "price": "19.99",
            "brand": "Acme",       # this will satisfy Brand (folded into aspects)
            "categoryId": "9344"   # required: Brand, Size; we're missing Size
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "aspects:missing:Size" in data["errors"]
    # No missing:brand since brand is folded into aspects
    assert "missing:brand" not in data["errors"]


def test_upsert_draft_only_inventory(monkeypatch, app_client):
    """
    /ebay/upsert/{sku}?mode=DRAFT should only PUT the inventory item.
    """
    import channels.ebay as ebay

    # avoid metadata GET during validate
    monkeypatch.setattr(ebay, "_required_aspects", lambda cat: [])

    # Patch tokens & policies
    monkeypatch.setattr(ebay, "_app_token", lambda scope="https://api.ebay.com/oauth/api_scope": "APP_TOK")
    monkeypatch.setattr(ebay, "_user_token", lambda scopes=None: "USER_TOK")
    monkeypatch.setattr(ebay, "_ensure_policies", lambda mkt: {
        "paymentPolicyId": "P1", "returnPolicyId": "R1", "fulfillmentPolicyId": "F1"
    })

    base = "https://api.sandbox.ebay.com"
    sku = "EB-SKU-001"

    mapping = {
        ("PUT", f"{base}/sell/inventory/v1/inventory_item/{sku}"): _Resp(200, {}),
        # No offer endpoints should be hit in DRAFT mode
    }
    stub = _HttpxClientStub(mapping=mapping)
    monkeypatch.setattr(ebay, "httpx", types.SimpleNamespace(Client=lambda timeout=None: stub))

    payload = {
        "title": "Premium Cotton Tee",
        "price": "19.99",
        "brand": "Acme",
        "quantity": 5,
        "categoryId": "9344",
        "aspects": {"Brand": ["Acme"], "Size": ["M"], "Color": ["Black"]},
    }
    resp = app_client.post(f"/ebay/upsert/{sku}?mode=DRAFT", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["mode"] == "DRAFT"

    # Verify only inventory PUT was called
    methods = [m for (m, _, _) in stub.calls]
    assert methods == ["PUT"]
    assert stub.calls[0][1].endswith(f"/sell/inventory/v1/inventory_item/{sku}")


def test_upsert_live_offer_create_and_publish(monkeypatch, app_client):
    """
    /ebay/upsert/{sku}?mode=LIVE should PUT inventory, create offer when none exists, then publish.
    """
    import channels.ebay as ebay

    # avoid metadata GET during validate
    monkeypatch.setattr(ebay, "_required_aspects", lambda cat: [])

    # Patch tokens & policies
    monkeypatch.setattr(ebay, "_app_token", lambda scope="https://api.ebay.com/oauth/api_scope": "APP_TOK")
    monkeypatch.setattr(ebay, "_user_token", lambda scopes=None: "USER_TOK")
    monkeypatch.setattr(ebay, "_ensure_policies", lambda mkt: {
        "paymentPolicyId": "P1", "returnPolicyId": "R1", "fulfillmentPolicyId": "F1"
    })

    base = "https://api.sandbox.ebay.com"
    sku = "EB-SKU-002"

    mapping = {
        # Inventory item
        ("PUT", f"{base}/sell/inventory/v1/inventory_item/{sku}"): _Resp(200, {}),
        # Offer lookup (no offers)
        ("GET", f"{base}/sell/inventory/v1/offer?sku={sku}"): _Resp(200, {"offers": []}),
        # Offer create -> returns offerId
        ("POST", f"{base}/sell/inventory/v1/offer"): _Resp(201, {"offerId": "O1"}),
        # Publish
        ("POST", f"{base}/sell/inventory/v1/offer/O1/publish"): _Resp(200, {}),
    }
    stub = _HttpxClientStub(mapping=mapping)
    monkeypatch.setattr(ebay, "httpx", types.SimpleNamespace(Client=lambda timeout=None: stub))

    payload = {
        "title": "Wireless Mouse",
        "price": "24.50",
        "brand": "TechCo",
        "quantity": 3,
        "categoryId": "31388",
        "aspects": {"Brand": ["TechCo"]},
    }
    resp = app_client.post(f"/ebay/upsert/{sku}?mode=LIVE", json=payload)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert data["mode"] == "LIVE"

    # Verify the call sequence: PUT inventory -> GET offer -> POST offer -> POST publish
    seq = [(m, u) for (m, u, _) in stub.calls]
    assert seq == [
        ("PUT", f"{base}/sell/inventory/v1/inventory_item/{sku}"),
        ("GET", f"{base}/sell/inventory/v1/offer?sku={sku}"),
        ("POST", f"{base}/sell/inventory/v1/offer"),
        ("POST", f"{base}/sell/inventory/v1/offer/O1/publish"),
    ]
