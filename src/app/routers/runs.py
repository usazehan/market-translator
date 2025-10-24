# src/app/routers/runs.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from storage.runs import list_runs, load_run

router = APIRouter(prefix="/runs")

@router.get("")
def list_runs_endpoint(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort: str = Query("desc", pattern="^(asc|desc)$"),
):
    return list_runs(limit=limit, offset=offset, sort=sort)

@router.get("/{run_id}")
def get_run(run_id: str):
    snap = load_run(run_id)
    if not snap:
        raise HTTPException(status_code=404, detail="run not found")
    return snap
