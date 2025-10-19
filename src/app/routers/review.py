# src/app/routers/review.py
from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

from pipeline.graph import run_pipeline
# Optional future: from storage.runs import load_run  # if you add snapshots

router = APIRouter(tags=["review"])

# ---------- Models ----------

class RejectItem(BaseModel):
    id: str
    errors: List[str] = Field(default_factory=list)
    # keep payload minimal; expose only what a fix-up UI needs
    channel_payload: Optional[Dict[str, Any]] = None

class ReviewRequest(BaseModel):
    catalog_path: str
    batch_size: int = 50
    extra: Optional[Dict[str, Any]] = None

class ReviewResponse(BaseModel):
    channel: str
    total_rejects: int
    total_filtered: int
    limit: int
    offset: int
    items: List[RejectItem]

# ---------- Helpers ----------

def _match_contains(rec: Dict[str, Any], needle: Optional[str]) -> bool:
    if not needle:
        return True
    needle = needle.lower()
    # search only in errors + a few safe fields in payload
    errors_text = " ".join(rec.get("errors", []))
    payload = rec.get("channel_payload") or {}
    # limit search to common text fields; avoids pulling huge blobs/PII
    fields = ["title", "description", "brand", "color", "size"]
    payload_text = " ".join(f"{k}:{payload.get(k, '')}" for k in fields if k in payload)
    hay = f"{errors_text} {payload_text}".lower()
    return needle in hay

def _match_id_like(rec: Dict[str, Any], id_like: Optional[str]) -> bool:
    if not id_like:
        return True
    return id_like.lower() in (rec.get("id") or "").lower()

def _match_code_prefix(rec: Dict[str, Any], code_pref: Optional[str]) -> bool:
    if not code_pref:
        return True
    errs = rec.get("errors", []) or []
    return any(e.startswith(code_pref) for e in errs)

# ---------- Route ----------

@router.post("/review/{channel}", response_model=ReviewResponse)
def review(
    channel: str,
    req: ReviewRequest,
    limit: int = Query(50, ge=1, le=500, description="Page size (1..500)"),
    offset: int = Query(0, ge=0, description="Zero-based offset"),
    contains: Optional[str] = Query(None, description="Substring search across errors + selected payload fields"),
    id_like: Optional[str] = Query(None, description="Substring match on item id"),
    code_pref: Optional[str] = Query(None, description="Error code prefix (e.g. 'schema:' or 'missing:')"),
    sort_by: Optional[str] = Query(None, pattern="^(id|errors)$", description="Sort by id or first error"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    # Optional future: run_id: Optional[str] = Query(None, description="Use a saved run snapshot instead of re-running"),
):
    """
    Returns only rejects for a run of the pipeline (dry-run).
    Note: currently re-executes the pipeline; consider persisting runs and adding run_id later.
    """
    # If you add snapshots later:
    # if run_id:
    #     snap = load_run(run_id)
    #     if not snap:
    #         raise HTTPException(status_code=404, detail="Run not found")
    #     rejects = snap.get("rejects", [])
    #     return _render_rejects(channel, rejects, ...)

    try:
        result = run_pipeline(
            channel=channel,
            catalog_path=req.catalog_path,
            batch_size=req.batch_size,
            dry_run=True,
            extra=req.extra or {},
        )
    except FileNotFoundError:
        raise HTTPException(status_code=400, detail="catalog_path not found")
    except Exception as ex:
        # Convert unexpected pipeline failures into a clean HTTP 500
        raise HTTPException(status_code=500, detail=f"pipeline_error:{type(ex).__name__}")

    rejects: List[Dict[str, Any]] = result.get("rejects", []) or []

    # filter
    filtered = [
        r for r in rejects
        if _match_contains(r, contains)
        and _match_id_like(r, id_like)
        and _match_code_prefix(r, code_pref)
    ]

    # sort
    if sort_by:
        reverse = (sort_dir == "desc")
        if sort_by == "id":
            filtered.sort(key=lambda r: (r.get("id") or ""), reverse=reverse)
        else:  # errors
            filtered.sort(key=lambda r: " ".join(r.get("errors", [])), reverse=reverse)

    total = len(filtered)
    start = offset
    end = min(offset + limit, total)
    page_dicts = filtered[start:end]

    # shape into models
    page = [
        RejectItem(
            id=str(d.get("id") or ""),
            errors=[str(e) for e in (d.get("errors") or [])],
            channel_payload=d.get("channel_payload") or None,
        )
        for d in page_dicts
    ]

    return ReviewResponse(
        channel=channel,
        total_rejects=len(rejects),
        total_filtered=total,
        limit=limit,
        offset=offset,
        items=page,
    )
