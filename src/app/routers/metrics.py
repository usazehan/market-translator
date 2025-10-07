from fastapi import APIRouter

router = APIRouter()

# Placeholder. In production, expose Prometheus metrics or summaries from storage.
@router.get("/")
def metrics():
    return {"accepted": 0, "rejected": 0, "throughput_per_min": 0}
