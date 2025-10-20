# src/channels/ebay.py
from __future__ import annotations

import os
import time
import json
from typing import Dict, Any, List, Tuple, Optional

import httpx

EBAY_BASE_URL = os.getenv("EBAY_BASE_URL", "https://api.sandbox.ebay.com")
EBAY_MARKETPLACE_ID = os.getenv("EBAY_MARKETPLACE_ID", "EBAY_US")
EBAY_LOCALE = os.getenv("EBAY_LOCALE")  # e.g., "en-US", "de-DE" (optional)

EBAY_CLIENT_ID = os.getenv("EBAY_CLIENT_ID")
EBAY_CLIENT_SECRET = os.getenv("EBAY_CLIENT_SECRET")
EBAY_REFRESH_TOKEN = os.getenv("EBAY_REFRESH_TOKEN")

# Optional policy overrides
OVERRIDE_PAYMENT = os.getenv("EBAY_PAYMENT_POLICY_ID")
OVERRIDE_RETURN = os.getenv("EBAY_RETURN_POLICY_ID")
OVERRIDE_FULFILL = os.getenv("EBAY_FULFILLMENT_POLICY_ID")

# ---- simple process-local caches ----
_token_cache: Dict[str, Tuple[float, str]] = {}               # key -> (exp_ts, token)
_policy_cache: Dict[str, Dict[str, str]] = {}                 # marketplaceId -> ids
_aspects_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}  # key -> (exp, aspects)

TOKEN_TTL = 45 * 60
ASPECTS_TTL = 6 * 60 * 60


def _basic_auth_header() -> str:
    import base64
    if not EBAY_CLIENT_ID or not EBAY_CLIENT_SECRET:
        raise RuntimeError("Missing EBAY_CLIENT_ID/EBAY_CLIENT_SECRET")
    token = base64.b64encode(f"{EBAY_CLIENT_ID}:{EBAY_CLIENT_SECRET}".encode()).decode()
    return f"Basic {token}"


def _app_token(scope: str = "https://api.ebay.com/oauth/api_scope") -> str:
    now = time.time()
    key = f"app:{scope}"
    exp, tok = _token_cache.get(key, (0.0, ""))
    if tok and now < exp:
        return tok
    headers = {"Authorization": _basic_auth_header(), "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "client_credentials", "scope": scope}
    with httpx.Client(timeout=30) as s:
        r = s.post(f"{EBAY_BASE_URL}/identity/v1/oauth2/token", data=data, headers=headers)
        r.raise_for_status()
        j = r.json()
    tok = j["access_token"]
    _token_cache[key] = (now + TOKEN_TTL, tok)
    return tok


def _user_token(scopes: Optional[List[str]] = None) -> str:
    if not EBAY_REFRESH_TOKEN:
        raise RuntimeError("Missing EBAY_REFRESH_TOKEN")
    now = time.time()
    scope_key = " ".join(scopes or [])
    key = f"user:{scope_key or 'default'}"
    exp, tok = _token_cache.get(key, (0.0, ""))
    if tok and now < exp:
        return tok
    headers = {"Authorization": _basic_auth_header(), "Content-Type": "application/x-www-form-urlencoded"}
    data = {"grant_type": "refresh_token", "refresh_token": EBAY_REFRESH_TOKEN}
    if scopes:
        data["scope"] = " ".join(scopes)
    with httpx.Client(timeout=30) as s:
        r = s.post(f"{EBAY_BASE_URL}/identity/v1/oauth2/token", data=data, headers=headers)
        r.raise_for_status()
        j = r.json()
    tok = j["access_token"]
    _token_cache[key] = (now + TOKEN_TTL, tok)
    return tok


def _h_app() -> dict:
    h = {
        "Authorization": f"Bearer {_app_token()}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID,
        "User-Agent": "market-translator/0.1",
    }
    if EBAY_LOCALE:
        h["Accept-Language"] = EBAY_LOCALE
    return h


def _h_user() -> dict:
    h = {
        "Authorization": f"Bearer {_user_token(scopes=[ 'https://api.ebay.com/oauth/api_scope/sell.inventory', 'https://api.ebay.com/oauth/api_scope/sell.account'])}",
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": EBAY_MARKETPLACE_ID,
        "User-Agent": "market-translator/0.1",
    }
    if EBAY_LOCALE:
        h["Accept-Language"] = EBAY_LOCALE
    return h


def _ensure_policies(marketplace_id: str) -> Dict[str, str]:
    if marketplace_id in _policy_cache:
        return _policy_cache[marketplace_id]

    ids = {
        "paymentPolicyId": OVERRIDE_PAYMENT or "",
        "fulfillmentPolicyId": OVERRIDE_FULFILL or "",
        "returnPolicyId": OVERRIDE_RETURN or "",
    }
    # if all overrides present, cache and return
    if all(ids.values()):
        _policy_cache[marketplace_id] = ids
        return ids

    with httpx.Client(timeout=30) as s:
        if not ids["paymentPolicyId"]:
            r = s.get(f"{EBAY_BASE_URL}/sell/account/v1/payment_policy",
                      headers=_h_user(), params={"marketplace_id": marketplace_id})
            if r.status_code == 200:
                arr = (r.json() or {}).get("paymentPolicies") or []
                if arr: ids["paymentPolicyId"] = arr[0].get("paymentPolicyId") or arr[0].get("id", "")
        if not ids["fulfillmentPolicyId"]:
            r = s.get(f"{EBAY_BASE_URL}/sell/account/v1/fulfillment_policy",
                      headers=_h_user(), params={"marketplace_id": marketplace_id})
            if r.status_code == 200:
                arr = (r.json() or {}).get("fulfillmentPolicies") or []
                if arr: ids["fulfillmentPolicyId"] = arr[0].get("fulfillmentPolicyId") or arr[0].get("id", "")
        if not ids["returnPolicyId"]:
            r = s.get(f"{EBAY_BASE_URL}/sell/account/v1/return_policy",
                      headers=_h_user(), params={"marketplace_id": marketplace_id})
            if r.status_code == 200:
                arr = (r.json() or {}).get("returnPolicies") or []
                if arr: ids["returnPolicyId"] = arr[0].get("returnPolicyId") or arr[0].get("id", "")

    _policy_cache[marketplace_id] = ids
    return ids


def _required_aspects(category_id: str) -> List[str]:
    """
    Use Taxonomy/Metadata to fetch aspects for the category and pick the required ones.
    Keys we rely on (stable in docs): aspectConstraint.aspectRequired,
    sometimes aspectConstraint.aspectUsage == 'REQUIRED',
    aspectConstraint.aspectEnabledForVariations for variation specifics. :contentReference[oaicite:0]{index=0}
    """
    now = time.time()
    key = f"{EBAY_MARKETPLACE_ID}:{category_id}"
    exp, cached = _aspects_cache.get(key, (0.0, []))
    if cached and now < exp:
        aspects = cached
    else:
        url = f"{EBAY_BASE_URL}/sell/metadata/v1/marketplace/{EBAY_MARKETPLACE_ID}/get_item_aspects_for_category"
        with httpx.Client(timeout=30) as s:
            r = s.get(url, headers=_h_app(), params={"category_id": category_id})
            if r.status_code != 200:
                return []
            aspects = (r.json() or {}).get("aspects") or []
        _aspects_cache[key] = (now + ASPECTS_TTL, aspects)

    required: List[str] = []
    for a in aspects:
        c = a.get("aspectConstraint", {}) or {}
        if c.get("aspectRequired") is True or c.get("aspectUsage") == "REQUIRED" or c.get("aspectEnabledForVariations") is True:
            name = a.get("localizedAspectName") or a.get("aspectName")
            if name:
                required.append(str(name))
    return required


def _normalize(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize incoming shape; ensure product.aspects carries Brand/Color/Size, etc.
    """
    prod = payload.get("product") or {}
    aspects: Dict[str, List[str]] = {}

    # Flatten aspects from either level
    in_aspects = (prod.get("aspects") or payload.get("aspects") or {}) if isinstance(prod.get("aspects") or payload.get("aspects"), dict) else {}

    for k, v in in_aspects.items():
        if not v:
            continue
        if isinstance(v, list):
            aspects[k] = [str(x) for x in v if str(x).strip()]
        else:
            aspects[k] = [str(v)]

    # Fold brand/color/size into aspects if provided flat
    brand = (prod.get("brand") or payload.get("brand") or "").strip()
    if brand and "Brand" not in {k.capitalize(): None for k in aspects.keys()}:
        aspects["Brand"] = [brand]

    color = (payload.get("color") or "").strip()
    if color and "Color" not in {k.capitalize(): None for k in aspects.keys()}:
        aspects["Color"] = [color]

    size = (payload.get("size") or "").strip()
    if size and "Size" not in {k.capitalize(): None for k in aspects.keys()}:
        aspects["Size"] = [size]

    title = (prod.get("title") or payload.get("title") or "").strip()
    desc = (prod.get("description") or payload.get("description") or "").strip()
    price = (payload.get("price") or "").strip()

    return {
        "title": title,
        "description": desc,
        "aspects": aspects,
        "price": price,
        "quantity": int(payload.get("quantity") or payload.get("qty") or 10),
        "categoryId": payload.get("categoryId") or payload.get("category_id"),
        "imageUrls": payload.get("imageUrls") or [],
        "currency": payload.get("currency") or "USD",
    }


class EbayClient:
    name = "ebay"

    @classmethod
    def from_env(cls) -> "EbayClient":
        # Compatibility with base.get_client if you wire it up later.
        return cls()

    # ---------- public API ----------
    def validate_listing(self, payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
        errs: List[str] = []
        norm = _normalize(payload)

        if not norm["title"]:
            errs.append("missing:title")
        if not norm["price"]:
            errs.append("missing:price")
        # Try to infer Brand from aspects
        has_brand = any(k.lower() == "brand" and v for k, v in (norm["aspects"] or {}).items())
        if not has_brand:
            errs.append("missing:brand")

        cat = norm.get("categoryId") or os.getenv("EBAY_DEFAULT_CATEGORY_ID") or ""
        if cat:
            req = _required_aspects(str(cat))
            have_keys = {k.lower() for k in (norm["aspects"] or {}).keys()}
            for name in req:
                if name.lower() not in have_keys:
                    errs.append(f"aspects:missing:{name}")

        return (len(errs) == 0), errs

    def upsert_listing(self, payload: Dict[str, Any], mode: str = "DRAFT") -> Tuple[bool, List[str]]:
        """
        DRAFT: PUT InventoryItem only.
        LIVE:  PUT InventoryItem -> create/update Offer -> publish.
        """
        ok, errs = self.validate_listing(payload)
        if not ok:
            return False, errs

        norm = _normalize(payload)
        sku = payload.get("sku") or payload.get("id")
        if not sku:
            return False, ["missing:sku"]

        # Guard price
        try:
            price_val = f"{float(norm['price']):.2f}"
        except Exception:
            return False, ["invalid:price"]

        # 1) Inventory Item
        inv = {
            "product": {
                "title": norm["title"],
                "description": norm["description"][:4000] if norm["description"] else "",
                "aspects": norm["aspects"] or {},
            },
            "availability": {"shipToLocationAvailability": {"quantity": norm["quantity"]}},
        }
        if norm["imageUrls"]:
            inv["product"]["imageUrls"] = norm["imageUrls"]

        with httpx.Client(timeout=60) as s:
            put_url = f"{EBAY_BASE_URL}/sell/inventory/v1/inventory_item/{sku}"
            r = s.put(put_url, headers=_h_user(), content=json.dumps(inv).encode("utf-8"))
            if not (200 <= r.status_code < 300):
                return False, [f"ebay:inventory_item:{r.status_code}"]

        if mode.upper() == "DRAFT":
            return True, []

        # 2) Offer create/update (LIVE only)
        pol = _ensure_policies(EBAY_MARKETPLACE_ID)
        category_id = norm.get("categoryId") or os.getenv("EBAY_DEFAULT_CATEGORY_ID") or ""
        if not category_id:
            return False, ["missing:categoryId_for_live"]

        offer = {
            "sku": sku,
            "marketplaceId": EBAY_MARKETPLACE_ID,
            "format": "FIXED_PRICE",
            "availableQuantity": norm["quantity"],
            "categoryId": str(category_id),
            "pricingSummary": {"price": {"value": price_val, "currency": norm["currency"]}},
            "listingPolicies": {
                "paymentPolicyId": pol.get("paymentPolicyId"),
                "returnPolicyId": pol.get("returnPolicyId"),
                "fulfillmentPolicyId": pol.get("fulfillmentPolicyId"),
            },
        }
        if norm["description"]:
            offer["listingDescription"] = norm["description"][:5000]

        with httpx.Client(timeout=60) as s:
            # Get existing offers for SKU
            get_url = f"{EBAY_BASE_URL}/sell/inventory/v1/offer?sku={sku}"
            r = s.get(get_url, headers=_h_user())
            if r.status_code not in (200, 204):
                return False, [f"ebay:offer_lookup:{r.status_code}"]
            offers = (r.json() or {}).get("offers", []) or []

            if offers:
                offer_id = offers[0]["offerId"]
                put_url = f"{EBAY_BASE_URL}/sell/inventory/v1/offer/{offer_id}"
                r = s.put(put_url, headers=_h_user(), content=json.dumps(offer).encode("utf-8"))
                if not (200 <= r.status_code < 300):
                    return False, [f"ebay:offer_update:{r.status_code}"]
            else:
                create_url = f"{EBAY_BASE_URL}/sell/inventory/v1/offer"
                r = s.post(create_url, headers=_h_user(), content=json.dumps(offer).encode("utf-8"))
                if not (200 <= r.status_code < 300):
                    return False, [f"ebay:offer_create:{r.status_code}"]
                offer_id = (r.json() or {}).get("offerId")

            # 3) Publish
            pub_url = f"{EBAY_BASE_URL}/sell/inventory/v1/offer/{offer_id}/publish"
            r = s.post(pub_url, headers=_h_user())
            if not (200 <= r.status_code < 300):
                return False, [f"ebay:offer_publish:{r.status_code}"]

        return True, []
