from pipeline.state import PipelineState

def reconcile_node(state: PipelineState) -> PipelineState:
    # In production, query channel to confirm final status and collect rejects.
    # For MVP we just return accumulated errors.
    return state
