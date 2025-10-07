# Placeholder: add your HF pipelines here (e.g., zero-shot, summarization, NER).
# Keep imports local inside functions so the service can run without HF installed.

from typing import Dict, Any
from pipeline.state import Item

def normalize_title_desc(item: Item, payload: Dict[str, Any]) -> Dict[str, Any]:
    # Stub: lower risk deterministic cleanup
    title = payload.get("title", "").strip()
    title = " ".join(title.split())
    payload["title"] = title[:200]
    desc = payload.get("description", "").strip()
    payload["description"] = desc
    return payload
