# Placeholder: add your HF pipelines here (e.g., zero-shot, summarization, NER).
# Keep imports local inside functions so the service can run without HF installed.

from typing import Dict, Any
from pipeline.state import Item
import ast, re

def normalize_title_desc(item: Item, payload: Dict[str, Any]) -> Dict[str, Any]:
    # Work on a copy to avoid in-place surprises
    out = dict(payload)

    # Title/desc cleanup
    title = " ".join((out.get("title") or "").split())[:200]
    out["title"] = title
    out["description"] = (out.get("description") or "").strip()

    # Bullet points: accept list/tuple or "['a','b']" / '["a","b"]' string
    bp = out.get("bullet_points")
    if isinstance(bp, str):
        try:
            lit = ast.literal_eval(bp)  # handles JSON-ish & Python lists
            if isinstance(lit, (list, tuple)):
                bp = list(dict.fromkeys(str(x).strip() for x in lit if str(x).strip()))
        except Exception:
            # also try semicolon-separated fallback
            parts = [p.strip() for p in bp.split(";") if p.strip()]
            bp = list(dict.fromkeys(parts)) if parts else bp
    if isinstance(bp, (list, tuple)):
        out["bullet_points"] = list(bp)[:5]  # gently cap to 5 to improve accept rate

    # Price → clean and format to "0.00" (keeps it channel-agnostic)
    price_raw = out.get("price")
    if price_raw is not None:
        try:
            # remove currency symbols/commas/spaces
            cleaned = re.sub(r"[^\d.\-]", "", str(price_raw))
            out["price"] = f"{float(cleaned):.2f}"
        except Exception:
            pass

    # eBay specifics like "k:v;k2:v2" -> {"k":"v", "k2":"v2"}
    specs = out.get("specifics")
    if isinstance(specs, str) and specs.strip():
        d = {}
        for pair in specs.split(";"):
            if ":" in pair:
                k, v = pair.split(":", 1)
                k, v = k.strip(), v.strip()
                if k:
                    d[k] = v
        if d:
            out["specifics"] = d

    # Light brand cleanup
    if "brand" in out and isinstance(out["brand"], str):
        out["brand"] = out["brand"].strip()

    return out