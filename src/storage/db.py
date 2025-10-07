# Placeholder storage layer; swap with Postgres/Redis as you scale.
from typing import Any

def save_event(event: str, payload: Any) -> None:
    # Extend to persist to a DB or queue
    pass
