from typing import Dict, Any, List, Tuple, Optional
import os

class ChannelClient:
    """Base no-op client used when no sandbox is configured."""
    name = "base"

    def validate_listing(self, payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
        # Minimal requireds; your pipeline validator should catch most things already.
        errors = []
        if not (payload.get("title") and str(payload.get("title")).strip()):
            errors.append("title:empty")
        if not payload.get("price"):
            errors.append("price:missing")
        else:
            try:
                if float(payload["price"]) <= 0:
                    errors.append("price:not_positive")
            except Exception:
                errors.append("price:not_numeric")
        return (len(errors) == 0), errors

    def upsert_listing(self, payload: Dict[str, Any]) -> bool:
        # Pretend success if minimal fields exist
        ok, _ = self.validate_listing(payload)
        return ok

def get_client(channel: str) -> ChannelClient:
    """Return a concrete client if sandbox env vars are present, else the stub."""
    ch = (channel or "").lower()
    try:
        if ch == "amazon" and os.getenv("AMAZON_BASE_URL"):
            from .amazon import AmazonSandboxClient
            return AmazonSandboxClient.from_env()
        if ch == "ebay" and os.getenv("EBAY_BASE_URL"):
            from .ebay import EbaySandboxClient
            return EbaySandboxClient.from_env()
    except Exception:
        # If anything goes wrong loading a real client, fall back to stub
        pass
    return ChannelClient()
