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

def _collect_error_strings(run_snapshot: Dict[str, Any]) -> List[str]:
    """
    Prefer errors from run['rejects'][i]['errors'] (already grouped by id).
    Fall back to run['errors'] (raw 'id: message' strings) if needed.
    """
    errs: List[str] = []
    rejects = run_snapshot.get("rejects") or []
    if rejects:
        for r in rejects:
            for e in (r.get("errors") or []):
                if e:
                    errs.append(str(e))
        return errs

    # Fallback: parse raw "id: message"
    for raw in (run_snapshot.get("errors") or []):
        try:
            _, msg = str(raw).split(":", 1)
            errs.append(msg.strip())
        except ValueError:
            errs.append(str(raw).strip())
    return errs

def _families(code: str) -> List[str]:
    """
    Break a code like 'schema:required:attributes/brand' into families:
      - 'schema'
      - 'schema:required'
    For 'aspects:missing:Color' -> 'aspects', 'aspects:missing'
    For 'missing:brand' -> 'missing'
    """
    parts = str(code).split(":")
    fams: List[str] = []
    if parts:
        fams.append(parts[0])
    if len(parts) >= 2:
        fams.append(":".join(parts[:2]))
    return fams

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
    top: int = Query(50, ge=1, le=500, description="Max rows for each histogram"),
):
    snap = load_run(run_id)
    if not snap:
        raise HTTPException(status_code=404, detail="No saved runs found" if run_id is None else "Run not found")

    codes = _collect_error_strings(snap)

    # Exact code histogram
    exact_ctr = Counter(codes)

    # Family histograms
    fam1_ctr: Counter[str] = Counter()
    fam2_ctr: Counter[str] = Counter()
    for c in codes:
        fams = _families(c)
        if len(fams) >= 1:
            fam1_ctr[fams[0]] += 1
        if len(fams) >= 2:
            fam2_ctr[fams[1]] += 1

    def _top(counter: Counter[str]) -> List[Dict[str, Any]]:
        return [{"code": k, "count": v} for k, v in counter.most_common(top)]

    return {
        "run_id": snap.get("run_id"),
        "channel": snap.get("channel"),
        "catalog_path": snap.get("catalog_path"),
        "catalog_sha256": (snap.get("catalog_fingerprint") or {}).get("sha256"),
        "counts": {
            "total_rejects": len(snap.get("rejects") or []),
            "total_errors": sum(exact_ctr.values()),
            "unique_error_codes": len(exact_ctr),
        },
        "histograms": {
            "exact": _top(exact_ctr),
            "families_level1": _top(fam1_ctr),  # e.g., 'missing', 'schema', 'aspects'
            "families_level2": _top(fam2_ctr),  # e.g., 'schema:required', 'aspects:missing'
        },
    }
