# src/channels/base.py
from typing import Dict, Any, List, Tuple
import os

class ChannelClient:
    name = "base"

    def validate_listing(self, payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
        errs = []
        if not (payload.get("title") or payload.get("attributes")):
            errs.append("missing:title_or_attributes")
        if not payload.get("price") and "attributes" not in payload:
            errs.append("missing:price_or_attributes")
        return (len(errs) == 0), errs

    def upsert_listing(self, payload: Dict[str, Any]) -> bool:
        # Pretend success if minimal fields exist
        ok, _ = self.validate_listing(payload)
        return ok

def _has_all(names: list[str]) -> bool:
    return all(os.getenv(n) for n in names)

def get_client(channel: str) -> ChannelClient:
    ch = (channel or "").lower()
    # Prefer Amazon SP-API if LWA creds + endpoint are set
    if ch == "amazon" and _has_all([
        "LWA_CLIENT_ID", "LWA_CLIENT_SECRET", "LWA_REFRESH_TOKEN",
        "SPAPI_HOST", "SELLER_ID", "MARKETPLACE_IDS"
    ]):
        from .amazon import AmazonSPAPIClient
        return AmazonSPAPIClient.from_env()
    
    # eBay Sell APIs (sandbox or prod)
    if ch == "ebay" and _has_all([
        "EBAY_BASE_URL", "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET",
        "EBAY_REFRESH_TOKEN", "EBAY_MARKETPLACE_ID"
    ]):
        from .ebay import EbayClient
        return EbayClient.from_env()
    
    return ChannelClient()
