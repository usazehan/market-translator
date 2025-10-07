import time
from typing import List
from pipeline.state import PipelineState, TranslatedItem
from rate_limit.limiter import get_limiter
from channels.base import get_client

def _simulate_upsert(batch: List[TranslatedItem], channel: str) -> List[str]:
    # Returns IDs that were 'upserted' successfully.
    # Replace this with the real channel client call.
    client = get_client(channel)
    ids = []
    for t in batch:
        ok = client.upsert_listing(t.channel_payload)
        if ok:
            ids.append(t.id)
    return ids

def throttle_and_upsert_node(state: PipelineState) -> PipelineState:
    limiter = get_limiter(state.channel)
    upserted = []
    for batch in state.batches:
        # Acquire capacity for the whole batch (simplified); per-item is also fine.
        with limiter():
            if state.dry_run:
                # simulate some work
                time.sleep(0.01)
                upserted.extend([t.id for t in batch])
            else:
                upserted.extend(_simulate_upsert(batch, state.channel))
    state.upserted_ids = upserted
    return state
