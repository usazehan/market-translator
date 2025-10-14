from __future__ import annotations
from typing import Dict, Any, List, Tuple
import time
import httpx
from jsonschema import Draft201909Validator as Validator, exceptions as js_exc

# Simple in-memory cache (productType + marketplaceIds) for ~1 hour
_CACHE: Dict[str, Dict[str, Any]] = {}
_TTL = 3600

def _cache_key(host: str, mids: List[str], product_type: str) -> str:
    mids_key = ",".join(sorted(mids))
    return f"{host}|{mids_key}|{product_type}"

def _get_cached(key: str) -> Dict[str, Any] | None:
    v = _CACHE.get(key)
    if v and time.time() < v.get("_exp", 0):
        return v["schema"]
    return None

def _put_cache(key: str, schema: Dict[str, Any]) -> None:
    _CACHE[key] = {"schema": schema, "_exp": time.time() + _TTL}

def fetch_ptd_schema(host: str, marketplace_ids: List[str], access_token: str, product_type: str) -> Dict[str, Any]:
    """
    Calls Product Type Definitions: GET /definitions/2020-09-01/productTypes/{productType}
    Returns the JSON Schema describing the 'attributes' object for that product type.
    """
    key = _cache_key(host, marketplace_ids, product_type)
    cached = _get_cached(key)
    if cached:
        return cached

    url = f"{host.rstrip('/')}/definitions/2020-09-01/productTypes/{product_type}"
    headers = {
        "x-amz-access-token": access_token,  # LWA token (no SigV4 needed)
        "accept": "application/json",
        "user-agent": "market-translator/0.1 (Language=Python)",
    }
    params = {
        "marketplaceIds": ",".join(marketplace_ids),
        "requirements": "LISTING",
    }
    with httpx.Client(timeout=15.0) as http:
        r = http.get(url, headers=headers, params=params)
        r.raise_for_status()
        data = r.json()
    # PTD response includes a 'schema' object — we’ll validate against this.
    schema = data.get("schema") or data
    _put_cache(key, schema)
    return schema

def _format_error(e: js_exc.ValidationError) -> str:
    """
    Make a compact, stable error code:
      schema:<validator>:<path>[:detail]
    Example: schema:required:attributes/brand
             schema:type:attributes/purchasable_offer -> array expected
    """
    path = "/".join(str(p) for p in e.path) or "<root>"
    # Trim verbose message while keeping signal
    detail = ""
    if e.validator == "required" and isinstance(e.validator_value, list):
        # Message often like "'brand' is a required property" — try to pull missing key
        # We’ll just emit the whole validator for now.
        pass
    elif e.validator == "enum":
        detail = ":invalid_enum"
    elif e.validator == "type":
        detail = f":expected_{e.validator_value}"
    elif e.validator == "minItems":
        detail = f":minItems_{e.validator_value}"
    elif e.validator == "maxItems":
        detail = f":maxItems_{e.validator_value}"
    elif e.validator == "pattern":
        detail = ":pattern_mismatch"
    return f"schema:{e.validator}:attributes/{path}{detail}"

def validate_attributes_with_ptd(
    host: str,
    marketplace_ids: List[str],
    access_token: str,
    product_type: str,
    attributes: Dict[str, Any],
) -> Tuple[bool, List[str]]:
    """
    Standard JSON Schema validation ONLY (ignores Amazon's custom vocabulary),
    which already catches most structural issues before you call Listings Items.
    """
    try:
        schema = fetch_ptd_schema(host, marketplace_ids, access_token, product_type)
    except Exception as ex:
        # If schema fetch fails, don't block — return a transport diagnostic and let API handle it.
        return False, [f"ptd_fetch:{type(ex).__name__}"]

    try:
        # PTD schema describes the 'attributes' object directly.
        validator = Validator(schema)
        errors = sorted(validator.iter_errors(attributes), key=lambda e: e.path)
        if not errors:
            return True, []
        return False, [_format_error(e) for e in errors]
    except js_exc.SchemaError:
        # If Amazon returns a schema draft or keyword our lib doesn't fully grok,
        # fall back to "ok" so we don't block uploads.
        return True, []
