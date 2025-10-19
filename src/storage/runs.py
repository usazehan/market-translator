from __future__ import annotations
import os, json, time, glob
from typing import Any, Dict, Optional

# storage/runs alongside src/
_BASE = os.path.dirname(os.path.dirname(__file__))        # -> src/
_RUNS_DIR = os.path.join(_BASE, "storage", "runs")
os.makedirs(_RUNS_DIR, exist_ok=True)

def new_run_id() -> str:
    # simple epoch-second id; swap for uuid if you prefer
    return str(int(time.time()))

def _run_path(run_id: str) -> str:
    return os.path.join(_RUNS_DIR, f"{run_id}.json")

def save_run(run_id: Optional[str], payload: Dict[str, Any]) -> str:
    """Persist a serializable snapshot."""
    rid = run_id or new_run_id()
    # also store run_id inside the snapshot for convenience
    payload = dict(payload)
    payload["run_id"] = rid
    with open(_run_path(rid), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
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
