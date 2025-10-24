from __future__ import annotations
from typing import Any, Dict, List, Optional
import os
import json
import time
import glob
import uuid
import hashlib

# storage/runs alongside src/
_BASE = os.path.dirname(os.path.dirname(__file__))        # -> src/
_RUNS_DIR = os.path.join(_BASE, "storage", "runs")
os.makedirs(_RUNS_DIR, exist_ok=True)

def new_run_id() -> str:
    """
    Sortable, low-collision run id: <epoch_ms>-<8char>
    Example: 1739999999999-b4f1a2c3
    """
    epoch_ms = int(time.time() * 1000)
    rnd = uuid.uuid4().hex[:8]
    return f"{epoch_ms}-{rnd}"

def _run_path(run_id: str) -> str:
    return os.path.join(_RUNS_DIR, f"{run_id}.json")

def _file_sha256(path: str, chunk_size: int = 1 << 20) -> Optional[str]:
    if not path or not os.path.exists(path) or not os.path.isfile(path):
        return None
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                b = f.read(chunk_size)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()
    except Exception:
        return None

def catalog_fingerprint(path: Optional[str]) -> Dict[str, Any]:
    """
    Return {sha256, size, mtime, exists} for the input file, all optional-friendly.
    """
    if not path:
        return {"exists": False, "sha256": None, "size": None, "mtime": None}
    try:
        exists = os.path.exists(path) and os.path.isfile(path)
        size = os.path.getsize(path) if exists else None
        mtime = os.path.getmtime(path) if exists else None
        sha256 = _file_sha256(path) if exists else None
        return {
            "exists": bool(exists),
            "sha256": sha256,
            "size": size,
            "mtime": mtime,
        }
    except Exception:
        return {"exists": False, "sha256": None, "size": None, "mtime": None}

def save_run(run_id: Optional[str], payload: Dict[str, Any]) -> str:
    """Persist a serializable snapshot."""
    rid = run_id or new_run_id()
    # also store run_id inside the snapshot for convenience
    snap = dict(payload)
    snap["run_id"] = rid
    
    snap.setdefault("channel", payload.get("channel"))
    if "catalog_path" in payload:
        snap["catalog_path"] = payload["catalog_path"]
    if "catalog_fingerprint" not in snap:
        # Let callers pass this in; otherwise compute best-effort
        snap["catalog_fingerprint"] = catalog_fingerprint(payload.get("catalog_path"))
        
    counts = (payload.get("counts") or {})
    snap.setdefault("counts", counts)
    snap.setdefault("rejects_count", len(payload.get("rejects", [])))
    snap.setdefault("errors_count", len(payload.get("errors", [])))
        
    with open(_run_path(rid), "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    return rid

def latest_run_id() -> Optional[str]:
    files = sorted(glob.glob(os.path.join(_RUNS_DIR, "*.json")))
    if not files:
        return None
    return os.path.splitext(os.path.basename(files[-1]))[0]

def load_run(run_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if run_id is None:
        run_id = latest_run_id()
        if not run_id:
            return None
    path = _run_path(run_id)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _summary_from_file(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            j = json.load(f)
        return summary_of_snapshot(j)
    except Exception:
        return None
    
def list_runs(limit: int = 50, offset: int = 0, sort: str = "desc") -> Dict[str, Any]:
    files = glob.glob(os.path.join(_RUNS_DIR, "*.json"))

    files.sort(reverse=(sort.lower() == "desc"))
    total = len(files)
    window = files[offset: offset + limit]
    items: List[Dict[str, Any]] = []
    for p in window:
        s = _summary_from_file(p)
        if s:
            items.append(s)
    return {"total": total, "limit": limit, "offset": offset, "items": items}

def summary_of_snapshot(j: Dict[str, Any]) -> Dict[str, Any]:
    cf = j.get("catalog_fingerprint") or {}
    counts = j.get("counts") or {}
    return {
        "run_id": j.get("run_id"),
        "created_at": j.get("created_at"),
        "channel": j.get("channel"),
        "catalog_path": j.get("catalog_path"),
        "catalog_sha256": cf.get("sha256"),
        "counts": {
            "input_items": counts.get("input_items", 0),
            "mapped": counts.get("mapped", 0),
            "valid": counts.get("valid", 0),
            "batches": counts.get("batches", 0),
            "upserted": counts.get("upserted", 0),
            "errors": counts.get("errors", 0),
        },
        "rejects_count": j.get("rejects_count", len(j.get("rejects", []))),
        "errors_count": j.get("errors_count", len(j.get("errors", []))),
    }