from __future__ import annotations
from fastapi import APIRouter, Body, Query, HTTPException
from channels.base import get_client

router = APIRouter(prefix="/ebay", tags=["ebay"])

def _client_or_501():
    c = get_client("ebay")
    # If env isn’t set, base client is returned; don’t pretend to upsert.
    if getattr(c, "name", "base") == "base":
        raise HTTPException(
            status_code=501,
            detail="eBay client not configured. Set EBAY_* env vars (BASE_URL, CLIENT_ID/SECRET, REFRESH_TOKEN, MARKETPLACE_ID).",
        )
    return c

@router.post("/validate")
def validate(payload: dict = Body(...)):
    c = _client_or_501()
    ok, errs = c.validate_listing(payload)
    return {"ok": ok, "errors": errs}

@router.post("/upsert/{sku}")
def upsert(
    sku: str,
    payload: dict = Body(...),
    mode: str = Query("DRAFT", pattern="^(LIVE|DRAFT)$"),
):
    c = _client_or_501()
    # convenience: let path param drive SKU; pass mode through to client
    merged = {**payload, "sku": sku, "mode": mode.upper()}
    ok = c.upsert_listing(merged)
    return {"ok": ok, "mode": mode.upper(), "sku": sku}
