# Placeholder: add your HF pipelines here (e.g., zero-shot, summarization, NER).
# Keep imports local inside functions so the service can run without HF installed.

from typing import Dict, Any
from pipeline.state import Item
import ast

def normalize_title_desc(item: Item, payload: Dict[str, Any]) -> Dict[str, Any]:
    # Title/desc cleanup
    title = " ".join((payload.get("title") or "").split())[:200]
    payload["title"] = title
    desc = (payload.get("description") or "").strip()

    # Bullet points: accept list or "['a','b']" string
    bp = payload.get("bullet_points")
    if isinstance(bp, str):
        try:
            lit = ast.literal_eval(bp)
            if isinstance(lit, (list, tuple)):
                payload["bullet_points"] = [str(x).strip() for x in lit]
        except Exception:
            pass
    
    # Price → string with two decimals (keeps it channel-agnostic)
    price = payload.get("price")
    try:
        payload["price"] = f"{float(price):.2f}"
    except Exception:
        pass
    return payload
