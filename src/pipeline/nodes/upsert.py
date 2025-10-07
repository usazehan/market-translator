import time
from typing import List
from pipeline.state import PipelineState, TranslatedItem
from rate_limit.limiter import get_limiter
from channels.base import get_client

def _validate_and_upsert(batch: List[TranslatedItem], channel: str, dry_run: bool, errors_out: list) -> List[str]:
    client = get_client(channel)
    ids: List[str] = []
    for t in batch:
        payload = t.channel_payload

        # Ask channel to validate before we upsert (guards against API rejects)
        ok, errs = client.validate_listing(payload)
        if not ok:
            errors_out.append(f"{t.id}: channel_validate:" + ",".join(errs))
            continue

        if dry_run:
            # pretend success
            time.sleep(0.005)
            ids.append(t.id)
            continue

        ok = client.upsert_listing(payload)
        if ok:
            ids.append(t.id)
        else:
            errors_out.append(f"{t.id}: upsert:failed")
    return ids

def throttle_and_upsert_node(state: PipelineState) -> PipelineState:
    limiter = get_limiter(state.channel)
    upserted: List[str] = []
    for batch in state.batches:
        with limiter():
            upserted.extend(_validate_and_upsert(batch, state.channel, state.dry_run, state.errors))
    state.upserted_ids = upserted
    return state
