# src/channels/amazon.py
from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import os, time, httpx
from models.ptd_validator import validate_attributes_with_ptd

class _LWA:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self._cached: Optional[str] = None
        self._exp: float = 0.0
        self._http = httpx.Client(timeout=10.0)

    def access_token(self) -> str:
        now = time.time()
        if self._cached and now < self._exp - 60:  # reuse until ~1 min before expiry
            return self._cached

        r = self._http.post(
            "https://api.amazon.com/auth/o2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data={
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
        )
        r.raise_for_status()
        data = r.json()
        self._cached = data["access_token"]
        self._exp = now + int(data.get("expires_in", 3600))
        return self._cached

class AmazonSPAPIClient:
    """
    Minimal SP-API adapter for Listings Items.

    validate_listing:
      - Sanity checks for productType/attributes
      - Optionally verifies productType exists via Product Type Definitions API

    upsert_listing:
      - PUT /listings/2021-08-01/items/{sellerId}/{sku}?marketplaceIds=...
      - Body should match Listings Items schema (productType, attributes, requirements)
    """
    name = "amazon-spapi"

    def __init__(
        self,
        host: str,
        seller_id: str,
        marketplace_ids: List[str],
        lwa: _LWA,
        user_agent: str = "market-translator/0.1 (Language=Python)",
        issue_locale: str = "en_US",
        timeout: float = 15.0,
    ):
        self.host = host.rstrip("/")
        self.seller_id = seller_id
        self.mids = marketplace_ids
        self.issue_locale = issue_locale
        self.ua = user_agent
        self.lwa = lwa
        self._http = httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls) -> "AmazonSPAPIClient":
        lwa = _LWA(
            client_id=os.environ["LWA_CLIENT_ID"],
            client_secret=os.environ["LWA_CLIENT_SECRET"],
            refresh_token=os.environ["LWA_REFRESH_TOKEN"],
        )
        mids = [m.strip() for m in os.environ["MARKETPLACE_IDS"].split(",") if m.strip()]
        return cls(
            host=os.environ["SPAPI_HOST"],
            seller_id=os.environ["SELLER_ID"],
            marketplace_ids=mids,
            lwa=lwa,
            user_agent=os.getenv("SPAPI_USER_AGENT", "market-translator/0.1 (Language=Python)"),
            issue_locale=os.getenv("SPAPI_ISSUE_LOCALE", "en_US"),
        )

    # ---------- helpers ----------
    def _headers(self) -> Dict[str, str]:
        return {
            "x-amz-access-token": self.lwa.access_token(),  # LWA token in header (no SigV4)
            "user-agent": self.ua,
            "content-type": "application/json",
            "accept": "application/json",
        }

    def _definitions_url(self, product_type: str) -> str:
        return f"{self.host}/definitions/2020-09-01/productTypes/{product_type}"

    def _put_item_url(self, sku: str) -> str:
        return f"{self.host}/listings/2021-08-01/items/{self.seller_id}/{sku}"

    # ---------- public interface ----------
    def validate_listing(self, payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Expect payload to be in Listings Items shape:
          { "sku": "...", "productType": "...", "attributes": { ... }, "requirements": "LISTING" }
        We only enforce basics here; full JSON-Schema validation can be added later.
        """
        errs: List[str] = []

        sku = payload.get("sku")
        if not sku or not str(sku).strip():
            errs.append("sku:missing")

        pt = payload.get("productType") or payload.get("product_type")
        if not pt:
            errs.append("productType:missing")

        attrs = payload.get("attributes")
        if not isinstance(attrs, dict):
            errs.append("attributes:missing_or_not_dict")

        if errs:
            return False, errs

        # Optional quick preflight: confirm productType exists for your marketplace(s)
        try:
            r = self._http.get(
                self._definitions_url(pt),
                params={"marketplaceIds": ",".join(self.mids), "requirements": "ENFORCED"},
                headers=self._headers(),
            )
            # 404 here means unknown/unsupported product type
            if r.status_code == 404:
                return False, [f"productType:unsupported:{pt}"]
            r.raise_for_status()
        except Exception:
            # Treat transport errors as soft failures; we'll let the upsert surface additional issues
            pass

        # Optional: enable via env flag to avoid surprises at first
        if os.getenv("SPAPI_SCHEMA_VALIDATE", "1") == "1":
            ok, schema_errs = validate_attributes_with_ptd(
                host=self.host,
                marketplace_ids=self.mids,
                access_token=self.lwa.access_token(),
                product_type=pt,
                attributes=attrs or {},
            )
            if not ok:
                # Prefix to distinguish client-side schema errors from API errors
                return False, [f"{e}" for e in schema_errs]
               
        return True, []

    def upsert_listing(self, payload: Dict[str, Any]) -> bool:
        """
        PUT Listings Item. Returns True on 2xx.
        """
        sku = payload["sku"]
        params = {
            "marketplaceIds": ",".join(self.mids),
            "issueLocale": self.issue_locale,
        }
        r = self._http.put(self._put_item_url(sku), json=payload, params=params, headers=self._headers())
        # Many validations are surfaced as 400 with a response body containing 'issues'
        if r.status_code // 100 == 2:
            return True
        # Optionally you could parse r.json().get("issues") and bubble them up
        return False
