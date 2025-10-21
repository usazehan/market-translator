# src/app/routers/amazon.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

import os
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict

from models.ptd_validator import validate_attributes_with_ptd

router = APIRouter(prefix="/amazon")

class AmazonPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    productType: str
    attributes: Dict[str, Any]

    # Optional knobs (fall back to env if not provided)
    marketplaceId: Optional[str] = None           # e.g., "ATVPDKIKX0DER"
    requirements: str = "LISTING"                 # LISTING | LISTING_OFFER_ONLY
    requirementsEnforced: str = "ENFORCED"        # ENFORCED | NOT_ENFORCED
    locale: Optional[str] = "en_US"


class AmazonValidateResponse(BaseModel):
    ok: bool
    errors: List[str] = []


_AMZ_AUTH_URL = "https://api.amazon.com/auth/o2/token"


def _lwa_access_token() -> str:
    """Exchange refresh token → LWA access token using env vars."""
    client_id = os.getenv("LWA_CLIENT_ID")
    client_secret = os.getenv("LWA_CLIENT_SECRET")
    refresh_token = os.getenv("LWA_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        raise HTTPException(
            status_code=500,
            detail="Missing LWA env vars (LWA_CLIENT_ID/LWA_CLIENT_SECRET/LWA_REFRESH_TOKEN).",
        )

    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    }
    with httpx.Client(timeout=30) as s:
        r = s.post(_AMZ_AUTH_URL, data=data)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"LWA token error {r.status_code}: {r.text}")
    return r.json()["access_token"]


def _resolve_host() -> str:
    host = os.getenv("SPAPI_HOST")
    if not host:
        raise HTTPException(status_code=500, detail="Missing SPAPI_HOST env var.")
    return host.rstrip("/")


def _resolve_marketplace_id(req_mp: Optional[str]) -> str:
    if req_mp:
        return req_mp
    env_mids = os.getenv("MARKETPLACE_IDS", "")
    if not env_mids:
        raise HTTPException(
            status_code=400,
            detail="marketplaceId not provided and MARKETPLACE_IDS env var is empty.",
        )
    # Use the first marketplace by default
    return env_mids.split(",")[0].strip()

@router.post("/validate", response_model=AmazonValidateResponse)
def amazon_validate(payload: AmazonPayload) -> AmazonValidateResponse:
    """
    Client-side validation against Amazon PTD schemas.
    Uses LWA → access token and GET /definitions/... to fetch JSON Schema,
    then validates { productType, attributes } (standard JSON Schema rules).
    """
    if os.getenv("SPAPI_SCHEMA_VALIDATE", "1") != "1":
        # Allow disabling via env
        return AmazonValidateResponse(ok=True, errors=[])

    host = _resolve_host()
    marketplace_id = _resolve_marketplace_id(payload.marketplaceId)
    access_token = _lwa_access_token()

    ok, issues = validate_attributes_with_ptd(
        host=host,
        marketplace_ids=[marketplace_id],
        access_token=access_token,
        product_type=payload.productType,
        attributes=payload.attributes or {},
    )
    return AmazonValidateResponse(ok=ok, errors=issues)
