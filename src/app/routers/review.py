# src/app/routers/review.py
from __future__ import annotations

from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from collections import Counter

from pipeline.graph import run_pipeline
from storage.runs import load_run

router = APIRouter(prefix="/review")

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

def _flatten_error_codes(rejects: List[Dict[str, Any]], raw_errors: List[str]) -> List[str]:
    """
    Build a flat list of error codes from snapshot:
    - Prefer structured rejects[i]["errors"] (list of strings)
    - Fall back to parsing raw "A: missing:title" strings if rejects is empty
    """
    out: List[str] = []
    
    # Process structured rejects first
    for r in rejects or []:
        for e in r.get("errors") or []:
            if not e:
                continue
            # If reject errors are "code" only, use as-is; if "id: code", strip id
            if ":" in e and not e.startswith(("missing:", "schema:", "aspects:", "required:")):
                # likely "ID: message" → keep message part
                _, tail = e.split(":", 1)
                out.append(tail.strip())
            else:
                out.append(e.strip())
    
    # Only use raw_errors as fallback if we got nothing from rejects
    if not out:
        for s in raw_errors or []:
            if ":" in s:
                _, tail = s.split(":", 1)
                out.append(tail.strip())
            else:
                out.append(s.strip())
    
    # normalize empties
    return [c for c in out if c]

def _family(code: str) -> str:
    # family is the prefix before the first colon, e.g. "missing", "schema", "aspects"
    i = code.find(":")
    return code[:i+1] if i != -1 else code

def _family_level1(code: str) -> str:
    """Extract first prefix: 'missing:brand' -> 'missing'"""
    i = code.find(":")
    return code[:i] if i != -1 else code

def _family_level2(code: str) -> str:
    """Extract first two prefixes: 'schema:required:attributes/brand' -> 'schema:required'"""
    parts = code.split(":")
    if len(parts) >= 2:
        return f"{parts[0]}:{parts[1]}"
    return code

# ---------- Route ----------

@router.post("/{channel}", response_model=ReviewResponse)
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
    run_id: Optional[str] = Query(None, description="Use a saved run snapshot instead of re-running"),
):
    # Prefer snapshot if run_id is provided
    data = None
    if run_id:
        data = load_run(run_id)
        if not data:
            raise HTTPException(status_code=404, detail="run_id not found")
    else:
        # Stateless mode: re-run the pipeline as dry-run
        try:
            data = run_pipeline(
                channel=channel,
                catalog_path=req.catalog_path,
                batch_size=req.batch_size,
                dry_run=True,
                extra=req.extra or {},
            )
        except FileNotFoundError:
            raise HTTPException(status_code=400, detail="catalog_path not found")
        except Exception as ex:
            raise HTTPException(status_code=500, detail=f"pipeline_error:{type(ex).__name__}")

    rejects: List[Dict[str, Any]] = data.get("rejects", []) or []

    # filtering
    filtered = [
        r for r in rejects
        if _match_contains(r, contains)
        and _match_id_like(r, id_like)
        and _match_code_prefix(r, code_pref)
    ]

    # sorting
    if sort_by:
        reverse = sort_dir == "desc"
        if sort_by == "id":
            filtered.sort(key=lambda r: (r.get("id") or ""), reverse=reverse)
        else:
            filtered.sort(key=lambda r: " ".join(r.get("errors", [])), reverse=reverse)

    total = len(filtered)
    page = filtered[offset: offset + limit]

    items = [
        RejectItem(
            id=str(p.get("id") or ""),
            errors=[str(e) for e in (p.get("errors") or [])],
            channel_payload=p.get("channel_payload") or None,
        )
        for p in page
    ]

    return ReviewResponse(
        run_id=data.get("run_id", "unknown"),
        channel=data.get("channel", channel),
        total_rejects=len(rejects),
        total_filtered=total,
        limit=limit,
        offset=offset,
        items=items,
    )
    
@router.get("/summary")
def review_summary(
    run_id: Optional[str] = Query(None, description="Run id to summarize; defaults to latest saved run"),
    top: Optional[int] = Query(
        None,
        ge=1,
        le=100,
        description="Return only the top-N error families by count (1..100). Omit for all."
    ),
):
    snap = load_run(run_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Run not found")

    rejects: List[Dict[str, Any]] = snap.get("rejects", [])
    raw_errors: List[str] = snap.get("errors", [])
    
    # 1) build exact codes and family buckets
    exact_codes = _flatten_error_codes(rejects, raw_errors)
    exact_hist = Counter(exact_codes)
    
    # Build hierarchical family histograms
    fam1_hist = Counter(_family_level1(c) for c in exact_codes)
    fam2_hist = Counter(_family_level2(c) for c in exact_codes)

    
    # 2) sort and limit
    fam1_items = sorted(fam1_hist.items(), key=lambda kv: (-kv[1], kv[0]))
    fam2_items = sorted(fam2_hist.items(), key=lambda kv: (-kv[1], kv[0]))
    
    if top is not None:
        fam1_items = fam1_items[:top]
        fam2_items = fam2_items[:top]
    
    exact_items = sorted(exact_hist.items(), key=lambda kv: (-kv[1], kv[0]))

    return {
        "run_id": snap.get("run_id"),
        "channel": snap.get("channel"),
        "catalog_path": snap.get("catalog_path"),
        "catalog_sha256": snap.get("catalog_fingerprint", {}).get("sha256"),
        "counts": {
            "total_rejects": len(rejects),
            "total_errors": len(exact_codes),
            "unique_error_codes": len(fam1_hist),  # families
        },
        "histograms": {
            "families_level1": [{"code": code, "count": count} for code, count in fam1_items],
            "families_level2": [{"code": code, "count": count} for code, count in fam2_items],
            "exact": [{"code": code, "count": count} for code, count in exact_items],
        },
    }
