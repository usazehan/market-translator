from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from pipeline.graph import run_pipeline

router = APIRouter()

class ReviewRequest(BaseModel):
    catalog_path: str
    batch_size: int = 50
    extra: Optional[Dict[str, Any]] = None

def _match_contains(rec: Dict[str, Any], needle: str) -> bool:
    if not needle:
        return True
    needle = needle.lower()
    # search in error codes/messages and in payload text
    errors_text = " ".join(rec.get("errors", []))
    payload_text = " ".join(f"{k}:{v}" for k, v in (rec.get("channel_payload") or {}).items())
    hay = f"{errors_text} {payload_text}".lower()
    return needle in hay

def _match_id_like(rec: Dict[str, Any], id_like: Optional[str]) -> bool:
    if not id_like:
        return True
    return id_like.lower() in (rec.get("id") or "").lower()

@router.post("/review/{channel}")
def review(
    channel: str,
    req: ReviewRequest,
    limit: int = Query(50, ge=1, le=500, description="Page size (1..500)"),
    offset: int = Query(0, ge=0, description="Zero-based offset"),
    contains: Optional[str] = Query(None, description="Substring to search in errors and payload"),
    id_like: Optional[str] = Query(None, description="Substring to search in item id"),
    sort_by: Optional[str] = Query(None, pattern="^(id|errors)$", description="Optional sort key"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
):
    # always dry-run for review
    result = run_pipeline(
        channel=channel,
        catalog_path=req.catalog_path,
        batch_size=req.batch_size,
        dry_run=True,
        extra=req.extra or {},
    )
    rejects: List[Dict[str, Any]] = result.get("rejects", [])

    # filter
    filtered = [
        r for r in rejects
        if _match_contains(r, contains) and _match_id_like(r, id_like)
    ]

    # sort
    if sort_by:
        reverse = sort_dir == "desc"
        if sort_by == "id":
            filtered.sort(key=lambda r: (r.get("id") or ""), reverse=reverse)
        elif sort_by == "errors":
            # sort by first error string
            filtered.sort(key=lambda r: " ".join(r.get("errors", [])), reverse=reverse)

    total = len(filtered)
    page = filtered[offset : offset + limit]

    return {
        "channel": channel,
        "total_rejects": len(rejects),
        "total_filtered": total,
        "limit": limit,
        "offset": offset,
        "items": page,
    }
