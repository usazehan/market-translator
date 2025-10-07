from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional, Dict, Any
from pipeline.graph import run_pipeline

router = APIRouter()

class ReviewRequest(BaseModel):
    catalog_path: str
    batch_size: int = 50
    extra: Optional[Dict[str, Any]] = None

@router.post("/review/{channel}")
def review(channel: str, req: ReviewRequest):
    # Always dry-run; we just want rejects
    result = run_pipeline(
        channel=channel,
        catalog_path=req.catalog_path,
        batch_size=req.batch_size,
        dry_run=True,
        extra=req.extra or {},
    )
    rejects = result.get("rejects", [])
    return {
        "channel": channel,
        "reject_count": len(rejects),
        "rejects": rejects,
    }
