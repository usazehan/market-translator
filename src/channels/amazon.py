from __future__ import annotations
from typing import Dict, Any, List, Tuple, Optional
import os
import httpx
from .base import ChannelClient

class AmazonSandboxClient(ChannelClient):
    """
    Minimal Amazon-like sandbox adapter.
    Expects a sandbox service that implements:
      POST {base_url}/validate  -> 200 {"ok": bool, "errors": [str]}
      POST {base_url}/listings  -> 200/201 on success
    Auth: Bearer token (AMAZON_TOKEN) if present.
    """

    name = "amazon-sandbox"

    def __init__(self, base_url: str, token: Optional[str] = None, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self._client = httpx.Client(timeout=self.timeout)

    @classmethod
    def from_env(cls) -> "AmazonSandboxClient":
        base = os.environ["AMAZON_BASE_URL"]
        token = os.getenv("AMAZON_TOKEN")
        return cls(base_url=base, token=token)

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json", "User-Agent": "market-translator/0.1"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def validate_listing(self, payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
        try:
            r = self._client.post(f"{self.base_url}/validate", json=payload, headers=self._headers())
            r.raise_for_status()
            data = r.json()
            return bool(data.get("ok", False)), list(data.get("errors", []))
        except Exception as e:
            # treat transport issues as validation failures with a diagnostic
            return False, [f"transport:{type(e).__name__}"]

    def upsert_listing(self, payload: Dict[str, Any]) -> bool:
        try:
            r = self._client.post(f"{self.base_url}/listings", json=payload, headers=self._headers())
            return r.status_code in (200, 201)
        except Exception:
            return False
