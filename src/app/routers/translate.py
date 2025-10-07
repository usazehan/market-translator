from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional, Dict, Any
from pipeline.graph import run_pipeline

router = APIRouter()

class TranslateRequest(BaseModel):
    catalog_path: str
    batch_size: int = 50
    extra: Optional[Dict[str, Any]] = None

@router.post("/translate/{channel}")
def translate(channel: str, req: TranslateRequest, dry_run: bool = Query(True)):
    result = run_pipeline(channel=channel, catalog_path=req.catalog_path, batch_size=req.batch_size, dry_run=dry_run, extra=req.extra or {})
    return result
