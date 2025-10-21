import os
import pytest

@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    # Default env for tests (override in individual tests as needed)
    monkeypatch.setenv("EBAY_BASE_URL", "https://api.sandbox.ebay.com")
    monkeypatch.setenv("EBAY_MARKETPLACE_ID", "EBAY_US")
    monkeypatch.setenv("EBAY_CLIENT_ID", "cid")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secret")
    monkeypatch.setenv("EBAY_REFRESH_TOKEN", "rtok")
    
    monkeypatch.setenv("SPAPI_HOST", "https://sandbox.sellingpartnerapi-na.amazon.com")
    monkeypatch.setenv("LWA_CLIENT_ID", "lwa_cid")
    monkeypatch.setenv("LWA_CLIENT_SECRET", "lwa_secret")
    monkeypatch.setenv("LWA_REFRESH_TOKEN", "lwa_rtok")
