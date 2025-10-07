from fastapi import FastAPI
from .routers import translate, health, metrics, review

app = FastAPI(title="Marketplace Schema Translator + Rate-Limit Agent")

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(metrics.router, prefix="/metrics", tags=["metrics"])
app.include_router(translate.router, prefix="", tags=["translate"])
app.include_router(review.router, tags=["review"])
