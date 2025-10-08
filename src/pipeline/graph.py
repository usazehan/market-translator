import csv
import json, os
from typing import Dict, Any, List
from langgraph.graph import StateGraph, END
from .state import PipelineState, Item, TranslatedItem
from .nodes.map_schema import map_schema_node
from .nodes.validate import validate_node
from .nodes.plan_batches import plan_batches_node
from .nodes.upsert import throttle_and_upsert_node
from .nodes.reconcile import reconcile_node

def _load_items(path: str) -> List[Item]:
    out: List[Item] = []
    ext = os.path.splitext(path)[1].lower()
    if ext == ".jsonl":
        with open(path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                # Store full JSON in attributes; id/title/desc are best-effort
                sku = str(obj.get("sku") or i)
                title = ""
                try:
                    title = obj.get("attributes",{}).get("item_name",[{}])[0].get("value","") or ""
                except Exception:
                    pass
                out.append(Item(id=sku, title=title, description="", attributes=obj))
        return out
    
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            out.append(Item(
                id=row.get("id") or row.get("sku") or row.get("ID") or str(len(out)+1),
                title=row.get("title", ""),
                description=row.get("description", ""),
                attributes={k: v for k, v in row.items() if k not in {"id","sku","ID","title","description"}}
            ))
    return out

def build_graph():
    g = StateGraph(PipelineState)
    g.add_node("map_schema", map_schema_node)
    g.add_node("validate", validate_node)
    g.add_node("plan_batches", plan_batches_node)
    g.add_node("throttle_and_upsert", throttle_and_upsert_node)
    g.add_node("reconcile", reconcile_node)

    g.set_entry_point("map_schema")
    g.add_edge("map_schema", "validate")
    g.add_edge("validate", "plan_batches")
    g.add_edge("plan_batches", "throttle_and_upsert")
    g.add_edge("throttle_and_upsert", "reconcile")
    g.add_edge("reconcile", END)

    return g.compile()

def run_pipeline(channel: str, catalog_path: str, batch_size: int, dry_run: bool, extra: Dict[str, Any]):
    items = _load_items(catalog_path)
    state = PipelineState(
        channel=channel,
        catalog_path=catalog_path,
        batch_size=batch_size,
        dry_run=dry_run,
        items=items,
    )
    app = build_graph()
    result = app.invoke(state)

    # NEW: LangGraph may return a dict; coerce to PipelineState for attribute access
    final_state = PipelineState(**result) if isinstance(result, dict) else result

    preview = [
        (m.model_dump() if hasattr(m, "model_dump") else m)
        for m in final_state.mapped[: min(5, len(final_state.mapped))]
    ]
    return {
        "channel": channel,
        "counts": {
            "input_items": len(items),
            "mapped": len(final_state.mapped),
            "valid": len(final_state.valid),
            "batches": len(final_state.batches),
            "upserted": len(final_state.upserted_ids),
            "errors": len(final_state.errors),
        },
        "preview_mapped": preview,
        "errors": final_state.errors,
        "rejects": [
            (r.model_dump() if hasattr(r, "model_dump") else r)
            for r in getattr(final_state, "rejects", [])
        ],
    }
