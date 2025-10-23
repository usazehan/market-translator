from __future__ import annotations

from importlib import reload
from typing import Any, Dict, Optional

import pytest


# ---- fixtures ----

@pytest.fixture
def app_client(monkeypatch):
    """
    Spin up FastAPI app and patch storage.runs.load_run so we can
    control the returned snapshot (both latest and specific run_id).
    """
    from fastapi.testclient import TestClient
    import src.app.main as main

    # Ensure routes are bound fresh
    reload(main)
    client = TestClient(main.app)
    return client


# ---- helpers ----

_FAKE_SNAPSHOT: Dict[str, Any] = {
    "run_id": "12345",
    "channel": "amazon",
    "catalog_path": "data/samples/catalog.csv",
    "catalog_fingerprint": {"sha256": "abc123"},
    # rejects already grouped by item id
    "rejects": [
        {"id": "SKU-001", "errors": ["missing:brand", "schema:required:attributes/brand"]},
        {"id": "SKU-002", "errors": ["aspects:missing:Color"]},
        {"id": "SKU-003", "errors": ["schema:type:attributes/offer:expected_array"]},
        {"id": "SKU-004", "errors": ["missing:brand"]},
    ],
    # keep raw errors for debugging; summary prefers rejects[].errors
    "errors": [
        "SKU-001: missing:brand",
        "SKU-001: schema:required:attributes/brand",
        "SKU-002: aspects:missing:Color",
        "SKU-003: schema:type:attributes/offer:expected_array",
        "SKU-004: missing:brand",
    ],
}


def _patch_load_run(monkeypatch, snapshot: Optional[Dict[str, Any]]):
    """
    Patch storage.runs.load_run to return `snapshot` for any input.
    load_run(None) => latest run in real app; here we return the same stub.
    """
    import src.app.routers.review as review_router
    monkeypatch.setattr(review_router, "load_run", lambda run_id=None: snapshot)


# ---- tests ----

def test_review_summary_latest_ok(monkeypatch, app_client):
    """
    GET /review/summary (no run_id) should return histograms from latest run.
    """
    _patch_load_run(monkeypatch, _FAKE_SNAPSHOT)

    resp = app_client.get("/review/summary")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    # top-level metadata
    assert data["run_id"] == "12345"
    assert data["channel"] == "amazon"
    assert data["catalog_path"] == "data/samples/catalog.csv"
    assert data["catalog_sha256"] == "abc123"
    assert data["counts"]["total_rejects"] == 4
    assert data["counts"]["total_errors"] == 5
    assert data["counts"]["unique_error_codes"] == 3  # missing:brand, aspects:missing:Color, schema:...

    # exact histogram should contain all three codes with correct counts
    exact = {row["code"]: row["count"] for row in data["histograms"]["exact"]}
    assert exact["missing:brand"] == 2
    assert exact["aspects:missing:Color"] == 1
    assert exact["schema:required:attributes/brand"] == 1
    assert exact["schema:type:attributes/offer:expected_array"] == 1

    # family level 1: missing, aspects, schema
    fam1 = {row["code"]: row["count"] for row in data["histograms"]["families_level1"]}
    assert fam1["missing"] == 2
    assert fam1["aspects"] == 1
    assert fam1["schema"] == 2  # two schema errors total

    # family level 2: schema:required and schema:type, aspects:missing
    fam2 = {row["code"]: row["count"] for row in data["histograms"]["families_level2"]}
    assert fam2["schema:required"] == 1
    assert fam2["schema:type"] == 1
    assert fam2["aspects:missing"] == 1


def test_review_summary_with_specific_run_id(monkeypatch, app_client):
    """
    GET /review/summary?run_id=XYZ should pass through to load_run('XYZ').
    """
    # Make a slightly different snapshot to verify plumbing
    alt = dict(_FAKE_SNAPSHOT)
    alt["run_id"] = "XYZ"
    alt["rejects"] = [{"id": "A", "errors": ["missing:title"]}]
    alt["errors"] = ["A: missing:title"]

    # Patch to return alt regardless of the run_id (we only assert the response)
    _patch_load_run(monkeypatch, alt)

    resp = app_client.get("/review/summary", params={"run_id": "XYZ"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["run_id"] == "XYZ"
    assert data["counts"]["total_rejects"] == 1
    exact = {row["code"]: row["count"] for row in data["histograms"]["exact"]}
    assert exact == {"missing:title": 1}


def test_review_summary_404_when_no_runs(monkeypatch, app_client):
    """
    If there is no saved run, return 404.
    """
    _patch_load_run(monkeypatch, None)
    resp = app_client.get("/review/summary")
    assert resp.status_code == 404
