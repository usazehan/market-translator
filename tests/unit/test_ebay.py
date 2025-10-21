# tests/test_ebay.py
from __future__ import annotations

import json
import types
from typing import Any, Dict, List

import pytest

import channels.ebay as ebay


# -----------------------
# Fixtures / test helpers
# -----------------------

@pytest.fixture(autouse=True)
def clear_ebay_caches(monkeypatch):
    # Ensure clean caches per test
    ebay._token_cache.clear()
    ebay._policy_cache.clear()
    ebay._aspects_cache.clear()
    # Default env so functions don't explode
    monkeypatch.setenv("EBAY_BASE_URL", "https://api.sandbox.ebay.com")
    monkeypatch.setenv("EBAY_MARKETPLACE_ID", "EBAY_US")
    # OAuth env (unused by validate_listing; used by _required_aspects header builder)
    monkeypatch.setenv("EBAY_CLIENT_ID", "cid")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    monkeypatch.setenv("EBAY_REFRESH_TOKEN", "rtok")
    yield
    ebay._token_cache.clear()
    ebay._policy_cache.clear()
    ebay._aspects_cache.clear()


def _make_httpx_get_stub(payload_by_url: Dict[str, Dict[str, Any]], status: int = 200):
    """
    Returns a function that mimics httpx.Client.get(...). We monkeypatch
    ebay.httpx.Client to use this stub for GET requests.
    """
    class _Resp:
        def __init__(self, url: str):
            self.status_code = status
            self._payload = payload_by_url.get(url, {})
        def json(self):
            return self._payload

    class _ClientStub:
        def __init__(self, timeout: int | float | None = None):
            self.timeout = timeout
        def __enter__(self):  # context manager support
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def get(self, url, headers=None, params=None):
            # Reconstruct the "full" URL including the params we care about
            if params:
                if "category_id" in params:
                    # The Metadata endpoint form in the code:
                    url = f"{url}?category_id={params['category_id']}"
                if "marketplace_id" in params:
                    url = f"{url}?marketplace_id={params['marketplace_id']}"
            return _Resp(url)

        # For code paths that might POST/PUT in other tests; not used here.
        def post(self, *a, **kw):  # pragma: no cover
            return _Resp("POST")
        def put(self, *a, **kw):   # pragma: no cover
            return _Resp("PUT")

    return _ClientStub


# -----------------------
# Tests for _required_aspects
# -----------------------

def test_required_aspects_picks_required(monkeypatch):
    """_required_aspects should return only required (or strongly required) names."""
    # Make header-building cheap
    monkeypatch.setenv("EBAY_CLIENT_ID", "x")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "y")
    monkeypatch.setenv("EBAY_MARKETPLACE_ID", "EBAY_US")
    monkeypatch.setenv("EBAY_BASE_URL", "https://api.sandbox.ebay.com")
    monkeypatch.setenv("EBAY_REFRESH_TOKEN", "dummy")
    monkeypatch.setattr(ebay, "_app_token", lambda: "TEST")  # <-- bypass OAuth
    
    base = "https://api.sandbox.ebay.com"
    mkt = "EBAY_US"
    cat = "9344"
    meta_url = f"{base}/sell/metadata/v1/marketplace/{mkt}/get_item_aspects_for_category?category_id={cat}"

    # Fake metadata payload including required + optional aspects
    payload = {
        "aspects": [
            {
                "localizedAspectName": "Brand",
                "aspectConstraint": {"aspectRequired": True, "itemToAspectCardinality": "SINGLE"},
            },
            {
                "localizedAspectName": "Size",
                "aspectConstraint": {"aspectUsage": "REQUIRED", "itemToAspectCardinality": "SINGLE"},
            },
            {
                "localizedAspectName": "Color",
                "aspectConstraint": {"aspectRequired": False, "itemToAspectCardinality": "SINGLE"},
            },
            {
                "localizedAspectName": "Material",
                "aspectConstraint": {"aspectEnabledForVariations": True},
            },
        ]
    }

    # Patch httpx.Client to serve our payload
    stub = _make_httpx_get_stub({meta_url: payload})
    monkeypatch.setattr(ebay, "httpx", types.SimpleNamespace(Client=stub))

    req = ebay._required_aspects(cat)
    # We consider "required", "usage == REQUIRED", and "enabled for variations" as required
    assert set(req) == {"Brand", "Size", "Material"}

    # Ensure cache is used (calling again returns the same without needing another GET).
    # We can't easily assert GET count without more plumbing, but at least ensure same result:
    again = ebay._required_aspects(cat)
    assert again == req


# -----------------------
# Tests for validate_listing
# -----------------------

def test_validate_listing_missing_minimums(monkeypatch):
    """
    Without title/price/brand and no categoryId, should emit missing errors.
    """
    client = ebay.EbayClient.from_env()

    ok, errs = client.validate_listing({"title": "", "price": "", "aspects": {}})
    assert not ok
    # brand check: since aspects empty and no 'brand' field, it should complain
    assert "missing:title" in errs
    assert "missing:price" in errs
    assert "missing:brand" in errs


def test_validate_listing_category_requires_aspects(monkeypatch):
    """
    If category requires Size and Brand, and payload provides title+price+brand,
    we should only see aspects:missing for those not present (e.g., Size).
    """
    # Force _required_aspects to a known list
    monkeypatch.setattr(ebay, "_required_aspects", lambda cat: ["Brand", "Size"])

    client = ebay.EbayClient.from_env()
    payload = {
        "title": "Premium Cotton Tee",
        "price": "19.99",
        "brand": "Acme",          # folded into aspects by _normalize
        "categoryId": "9344",
        # aspects has only Brand (implicit from 'brand' field)
    }
    ok, errs = client.validate_listing(payload)
    assert not ok
    # 'Brand' satisfied via brand->aspects folding; 'Size' missing
    assert "aspects:missing:Size" in errs
    # And no 'missing:brand' since it’s folded
    assert "missing:brand" not in errs


def test_validate_listing_case_insensitive_aspects(monkeypatch):
    """
    Required 'Color' should be satisfied if payload provides 'color' aspect key (case-insensitive).
    """
    monkeypatch.setattr(ebay, "_required_aspects", lambda cat: ["Color"])

    client = ebay.EbayClient.from_env()
    payload = {
        "title": "Bottle",
        "price": "9.99",
        "categoryId": "179961",
        "brand": "Acme",                              # add this
        "aspects": {"color": ["Blue"]},              # lower-case key to test case-insensitive match
    }
    ok, errs = client.validate_listing(payload)
    assert ok
    assert errs == []
