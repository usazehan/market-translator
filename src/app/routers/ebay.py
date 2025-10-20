# src/app/routers/ebay.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from channels.ebay import EbayClient, _ensure_policies, _required_aspects

router = APIRouter(prefix="/ebay", tags=["ebay"])
client = EbayClient.from_env()

class EbayPayload(BaseModel):
    sku: Optional[str] = None
    id: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    brand: Optional[str] = None
    price: Optional[str] = None
    currency: Optional[str] = "USD"
    quantity: Optional[int] = 1
    categoryId: Optional[str] = None
    aspects: Optional[Dict[str, List[str]]] = None
    # allow extra keys for forward-compat
    class Config:
        extra = "allow"

@router.post("/validate")
def validate(payload: EbayPayload):
    ok, errs = client.validate_listing(payload.dict(exclude_none=True))
    return {"ok": ok, "errors": errs}

@router.post("/upsert/{sku}")
def upsert(
    sku: str,
    payload: EbayPayload,
    mode: str = Query("DRAFT", pattern="^(DRAFT|LIVE)$"),
):
    data = payload.dict(exclude_none=True)
    data.setdefault("sku", sku)
    ok, errs = client.upsert_listing(data, mode=mode.upper())
    if not ok and not errs:
        raise HTTPException(status_code=502, detail="ebay_upsert_failed")
    return {"ok": ok, "errors": errs, "mode": mode.upper(), "sku": sku}

@router.get("/policies")
def get_policies():
    # warms cache; returns ids in use
    from channels.ebay import EBAY_MARKETPLACE_ID
    ids = _ensure_policies(EBAY_MARKETPLACE_ID)
    return {"marketplaceId": EBAY_MARKETPLACE_ID, "policies": ids}

@router.get("/aspects/{category_id}")
def get_required_aspects(category_id: str):
    req = _required_aspects(category_id)
    return {"categoryId": category_id, "required_aspects": req}

@router.post("/cache/clear")
def clear_cache():
    # local-dev helper to reset caches if you change env/account
    from channels.ebay import _token_cache, _policy_cache, _aspects_cache
    _token_cache.clear()
    _policy_cache.clear()
    _aspects_cache.clear()
    return {"cleared": True}
