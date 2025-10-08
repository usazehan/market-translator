from pipeline.state import PipelineState, TranslatedItem
from schema.mapping import loader as mapping_loader
from dspylocal.normalizer import normalize_fields

def map_schema_node(state: PipelineState) -> PipelineState:
    # Pass-through mode for pre-mapped SP-API JSONL
    if (state.extra or {}).get("input_format") == "spapi-jsonl":
        mapped = []
        for it in state.items:
            payload = it.attributes  # each Item.attributes holds the JSON object from the .jsonl line
            sku = payload.get("sku") or it.id
            mapped.append(TranslatedItem(id=str(sku), channel_payload=payload))
        state.mapped = mapped
        return state
    
    mapping = mapping_loader.load_mapping(state.channel)
    mapped = []
    for it in state.items:
        # Basic mapping via YAML + DSPy normalizer to fill/clean fields
        payload = {}
        for target_field, rule in mapping.items():
            if isinstance(rule, str):
                # direct/alias mapping from attributes/title/description
                payload[target_field] = it.attributes.get(rule) or getattr(it, rule, "")
            elif isinstance(rule, dict):
                src = rule.get("source")
                default = rule.get("default", "")
                val = it.attributes.get(src) or getattr(it, src, default)
                payload[target_field] = val
            else:
                payload[target_field] = ""
        # Run light normalization (title, bullets, brand, etc.)
        payload = normalize_fields(it, payload)
        mapped.append(TranslatedItem(id=it.id, channel_payload=payload))
    state.mapped = mapped
    return state
