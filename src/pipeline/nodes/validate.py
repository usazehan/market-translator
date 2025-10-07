from pipeline.state import PipelineState, TranslatedItem

# You can expand these per-channel requirements.
REQUIRED = {
    "amazon": ["title", "brand", "price"],
    "ebay": ["title", "price"],
}

def validate_node(state: PipelineState) -> PipelineState:
    req = REQUIRED.get(state.channel, ["title"])
    valid, errors = [], []
    for item in state.mapped:
        payload = item.channel_payload
        missing = [k for k in req if not payload.get(k)]
        if missing:
            errors.append(f"{item.id}: missing {missing}")
            continue
        valid.append(item)
    state.valid = valid
    state.errors.extend(errors)
    return state
