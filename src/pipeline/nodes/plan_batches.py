from pipeline.state import PipelineState

def plan_batches_node(state: PipelineState) -> PipelineState:
    # naive fixed-size batches; the rate limiter will enforce window constraints
    items = state.valid
    bs = state.batch_size or 50
    state.batches = [items[i:i+bs] for i in range(0, len(items), bs)]
    return state
