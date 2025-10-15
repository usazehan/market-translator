# src/channels/ebay.py
# eBay Sell API client matching your base.py interface:
#   validate_listing(payload) -> (ok, errors)
#   upsert_listing(payload)   -> ok
#
# Uses:
#  - OAuth2 app token for taxonomy/metadata
#  - OAuth2 user token (via refresh token) for inventory/offer
#  - Draft offers by default; publish when payload.get("mode") == "LIVE"

from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import os
import time
import json
import httpx


def _env(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    if v is None or v == "":
        raise RuntimeError(f"Missing env var: {name}")
    return v


class _EbayAuth:
    def __init__(self, base_url: str, client_id: str, client_secret: str, refresh_token: str) -> None:
        self.base = base_url.rstrip("/")
        self.cid  = client_id
        self.csec = client_secret
        self.refresh = refresh_token
        self._app_tok: Optional[str] = None
        self._app_exp: float = 0.0
        self._user_tok: Optional[str] = None
        self._user_exp: float = 0.0

    def _token(self, grant_type: str, scope: str, refresh_token: Optional[str] = None) -> dict:
        url = f"{self.base}/identity/v1/oauth2/token"
        data = {"grant_type": grant_type, "scope": scope}
        if refresh_token:
            data["refresh_token"] = refresh_token
        with httpx.Client(timeout=30) as s:
            r = s.post(url, data=data, auth=(self.cid, self.csec),
                       headers={"Content-Type": "application/x-www-form-urlencoded"})
            r.raise_for_status()
            return r.json()

    def app_token(self) -> str:
        now = time.time()
        if self._app_tok and now < self._app_exp - 60:
            return self._app_tok
        scopes = "https://api.ebay.com/oauth/api_scope"
        j = self._token("client_credentials", scopes)
        self._app_tok = j["access_token"]
        self._app_exp = now + float(j.get("expires_in", 7200))
        return self._app_tok

    def user_token(self) -> str:
        now = time.time()
        if self._user_tok and now < self._user_exp - 60:
            return self._user_tok
        scopes = " ".join([
            "https://api.ebay.com/oauth/api_scope/sell.inventory",
            "https://api.ebay.com/oauth/api_scope/sell.account",
        ])
        j = self._token("refresh_token", scopes, refresh_token=self.refresh)
        self._user_tok = j["access_token"]
        self._user_exp = now + float(j.get("expires_in", 7200))
        return self._user_tok


class EbayClient:
    name = "ebay"

    def __init__(self, *, base_url: str, marketplace_id: str, auth: _EbayAuth):
        self.base = base_url.rstrip("/")
        self.market = marketplace_id
        self.auth = auth

    @classmethod
    def from_env(cls) -> "EbayClient":
        base = _env("EBAY_BASE_URL")
        cid  = _env("EBAY_CLIENT_ID")
        csec = _env("EBAY_CLIENT_SECRET")
        rtok = _env("EBAY_REFRESH_TOKEN")
        market = _env("EBAY_MARKETPLACE_ID")
        return cls(base_url=base, marketplace_id=market, auth=_EbayAuth(base, cid, csec, rtok))

    # ---------- headers ----------
    def _h_app(self) -> dict:
        return {
            "Authorization": f"Bearer {self.auth.app_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": self.market,
            "User-Agent": "market-translator/0.1",
        }

    def _h_user(self) -> dict:
        return {
            "Authorization": f"Bearer {self.auth.user_token()}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-EBAY-C-MARKETPLACE-ID": self.market,
            "User-Agent": "market-translator/0.1",
        }

    # ---------- metadata/aspects ----------
    def _required_aspects(self, category_id: str) -> List[str]:
        url = f"{self.base}/sell/metadata/v1/marketplace/{self.market}/get_item_aspects_for_category"
        with httpx.Client(timeout=30) as s:
            r = s.get(url, headers=self._h_app(), params={"category_id": category_id})
            if r.status_code != 200:
                return []
            data = r.json()
        req: List[str] = []
        for a in data.get("aspects", []):
            c = a.get("aspectConstraint", {})
            if c.get("aspectRequired") or c.get("aspectRequiredForMultipleVariations"):
                name = a.get("localizedAspectName") or a.get("aspectName")
                if name:
                    req.append(name)
        return req

    # ---------- public API ----------
    def validate_listing(self, payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Cheap guards + optional aspects check (if categoryId is provided)."""
        errs: List[str] = []
        norm = self._normalize(payload)

        if not norm["title"]:
            errs.append("required:title")
        if not norm["price"]:
            errs.append("required:price")
        if not norm["brand"]:
            errs.append("required:brand")

        cat = norm.get("categoryId") or os.getenv("EBAY_DEFAULT_CATEGORY_ID") or ""
        if cat:
            required = set(self._required_aspects(cat))
            have = set((norm.get("aspects") or {}).keys())
            missing = [x for x in sorted(required) if x not in have]
            if missing:
                errs.append(f"aspects:missing:{','.join(missing)}")

        return (len(errs) == 0, errs)

    def upsert_listing(self, payload: Dict[str, Any]) -> bool:
        """
        InventoryItem -> Offer -> (maybe) Publish
        - pulls SKU from payload["sku"] or ["id"].
        - if payload["mode"] == "LIVE" publish; otherwise leave as draft.
        """
        norm = self._normalize(payload)
        sku  = payload.get("sku") or payload.get("id")
        if not sku:
            # many of your pipeline items already have id; surface clearly if not
            return False

        # 1) Inventory Item
        inv = self._to_inventory_item(norm)
        with httpx.Client(timeout=60) as s:
            r = s.put(f"{self.base}/sell/inventory/v1/inventory_item/{sku}",
                      headers=self._h_user(), content=json.dumps(inv).encode("utf-8"))
            if not (200 <= r.status_code < 300):
                return False

        # 2) Offer (create)
        pol = self._find_policies()
        offer = self._to_offer(norm, sku, pol)
        with httpx.Client(timeout=60) as s:
            r = s.post(f"{self.base}/sell/inventory/v1/offer",
                       headers=self._h_user(), content=json.dumps(offer).encode("utf-8"))
            if not (200 <= r.status_code < 300):
                return False
            offer_id = (r.json() or {}).get("offerId")

        # 3) Publish only when LIVE requested
        if (payload.get("mode") or "").upper() == "LIVE" and offer_id:
            with httpx.Client(timeout=30) as s:
                r = s.post(f"{self.base}/sell/inventory/v1/offer/{offer_id}/publish",
                           headers=self._h_user())
                return 200 <= r.status_code < 300

        return True  # draft created successfully

    # ---------- shaping helpers ----------
    def _normalize(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prod = payload.get("product") or {}
        if prod:
            title = prod.get("title") or ""
            brand = prod.get("brand") or (prod.get("aspects") or {}).get("Brand", [""])[0] if isinstance((prod.get("aspects") or {}).get("Brand"), list) else ""
            desc  = prod.get("description") or ""
            aspects = prod.get("aspects") or {}
            price = payload.get("price") or ""
        else:
            title = payload.get("title") or ""
            brand = payload.get("brand") or ""
            desc  = payload.get("description") or ""
            aspects = {}
            if payload.get("color"): aspects["Color"] = [str(payload["color"])]
            if payload.get("size"):  aspects["Size"]  = [str(payload["size"])]
            price = payload.get("price") or ""
        return {
            "title": title,
            "brand": brand,
            "description": desc,
            "aspects": aspects,
            "price": str(price),
            "quantity": int(payload.get("quantity") or payload.get("qty") or 10),
            "categoryId": payload.get("categoryId"),
            "imageUrls": payload.get("imageUrls") or [],
            "gtin": payload.get("gtin") or payload.get("upc") or "",
        }

    def _to_inventory_item(self, norm: Dict[str, Any]) -> Dict[str, Any]:
        product = {
            "title": norm["title"],
            "description": norm["description"],
            "brand": norm["brand"],
            "aspects": norm["aspects"] or {},
        }
        if norm["imageUrls"]:
            product["imageUrls"] = norm["imageUrls"]
        return {
            "product": product,
            "availability": {
                "shipToLocationAvailability": {"quantity": norm["quantity"]}
            }
        }

    def _to_offer(self, norm: Dict[str, Any], sku: str, pol: Dict[str, str]) -> Dict[str, Any]:
        price = {"value": f"{float(norm['price']):.2f}", "currency": "USD"}  # adjust if needed
        offer = {
            "sku": sku,
            "marketplaceId": self.market,
            "format": "FIXED_PRICE",
            "availableQuantity": norm["quantity"],
            "pricingSummary": {"price": price},
            "listingPolicies": {
                "paymentPolicyId": pol.get("paymentPolicyId"),
                "fulfillmentPolicyId": pol.get("fulfillmentPolicyId"),
                "returnPolicyId": pol.get("returnPolicyId"),
            }
        }
        cat = norm.get("categoryId") or os.getenv("EBAY_DEFAULT_CATEGORY_ID") or ""
        if cat:
            offer["categoryId"] = cat
        if norm["description"]:
            offer["listingDescription"] = norm["description"][:4000]
        # drop Nones/empties
        offer["listingPolicies"] = {k: v for k, v in offer["listingPolicies"].items() if v}
        return offer

    def _find_policies(self) -> Dict[str, str]:
        ids = {
            "paymentPolicyId": os.getenv("EBAY_PAYMENT_POLICY_ID") or "",
            "fulfillmentPolicyId": os.getenv("EBAY_FULFILLMENT_POLICY_ID") or "",
            "returnPolicyId": os.getenv("EBAY_RETURN_POLICY_ID") or "",
        }
        if all(ids.values()):
            return ids
        # otherwise pick the first policy in each list
        try:
            with httpx.Client(timeout=30) as s:
                if not ids["paymentPolicyId"]:
                    r = s.get(f"{self.base}/sell/account/v1/payment_policy",
                              headers=self._h_user(), params={"marketplace_id": self.market})
                    if r.status_code == 200 and r.json().get("paymentPolicies"):
                        ids["paymentPolicyId"] = r.json()["paymentPolicies"][0]["paymentPolicyId"]
                if not ids["fulfillmentPolicyId"]:
                    r = s.get(f"{self.base}/sell/account/v1/fulfillment_policy",
                              headers=self._h_user(), params={"marketplace_id": self.market})
                    if r.status_code == 200 and r.json().get("fulfillmentPolicies"):
                        ids["fulfillmentPolicyId"] = r.json()["fulfillmentPolicies"][0]["fulfillmentPolicyId"]
                if not ids["returnPolicyId"]:
                    r = s.get(f"{self.base}/sell/account/v1/return_policy",
                              headers=self._h_user(), params={"marketplace_id": self.market})
                    if r.status_code == 200 and r.json().get("returnPolicies"):
                        ids["returnPolicyId"] = r.json()["returnPolicies"][0]["returnPolicyId"]
        except Exception:
            pass
        return ids
