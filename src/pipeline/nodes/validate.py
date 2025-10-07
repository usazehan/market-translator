from typing import List, Tuple
from pipeline.state import PipelineState, TranslatedItem

# Base requireds; you can extend per channel.
REQUIRED = {
    "amazon": ["title", "brand", "price"],
    "ebay": ["title", "price"],
}

# --------- helpers ---------
def _missing_fields(payload: dict, fields: List[str]) -> List[str]:
    miss = []
    for f in fields:
        v = payload.get(f)
        if v is None:
            miss.append(f)
            continue
        if isinstance(v, str) and not v.strip():
            miss.append(f)
    return miss

def _validate_price(payload: dict) -> Tuple[bool, str]:
    val = payload.get("price", None)
    try:
        price = float(val)
    except (TypeError, ValueError):
        return False, "price:not_numeric"
    if price <= 0:
        return False, "price:not_positive"
    return True, ""

def _validate_title(payload: dict, max_len: int = 200) -> Tuple[bool, str]:
    t = str(payload.get("title", "") or "")
    if not t:
        return False, "title:empty"
    if len(t) > max_len:
        return False, f"title:too_long({len(t)}>{max_len})"
    return True, ""

def _validate_bullets(payload: dict, max_count: int = 5) -> Tuple[bool, str]:
    b = payload.get("bullet_points")
    if b is None:
        return True, ""
    if isinstance(b, (list, tuple)) and len(b) > max_count:
        return False, f"bullet_points:too_many({len(b)}>{max_count})"
    # strings are allowed (normalizer may convert later)
    return True, ""

# --------- main node ---------
def validate_node(state: PipelineState) -> PipelineState:
    channel = (state.channel or "").lower()
    req = REQUIRED.get(channel, ["title"])

    valid: List[TranslatedItem] = []
    errors: List[str] = []

    for item in state.mapped:
        payload = item.channel_payload
        item_errs: List[str] = []

        # required presence
        missing = _missing_fields(payload, req)
        if missing:
            item_errs.append("missing:" + ",".join(missing))

        # common checks
        ok, msg = _validate_price(payload)
        if not ok:
            item_errs.append(msg)

        ok, msg = _validate_title(payload)
        if not ok:
            item_errs.append(msg)

        # channel-specific checks
        if channel == "amazon":
            ok, msg = _validate_bullets(payload, max_count=5)
            if not ok:
                item_errs.append(msg)

        if item_errs:
            errors.append(f"{item.id}: " + "; ".join(item_errs))
        else:
            valid.append(item)

    state.valid = valid
    state.errors.extend(errors)
    return state