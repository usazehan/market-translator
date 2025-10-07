# Marketplace Schema Translator + Rate-Limit Agent

A production-leaning **MVP** that converts a source merchant catalog into channel-specific listings
(e.g., Amazon, eBay) using:
- **Hugging Face** (attribute extraction/normalization wrappers)
- **LangChain + LangGraph** (deterministic, debuggable workflow)
- **DSPy** (data-aware prompt/program optimization on a small labeled set)
- **FastAPI** (simple service surface)

> Goal: translate → validate → (optionally) enrich → throttle → upsert — with metrics and dry-run.

---

## Quickstart

```bash
# 1) Create and activate a venv (or use uv/pipx as you prefer).
python -m venv .venv && source .venv/bin/activate

# 2) Install
pip install -e .

# 3) Run the API
uvicorn src.app.main:app --reload

# 4) Try the dry-run translate (uses sample catalog):
#    POST /translate/{channel}?dry_run=true
#    Body: { "catalog_path": "data/samples/catalog_sample.csv" }
```

Channels scaffolded: **amazon**, **ebay** (stub clients).  
Storage: in-memory + local files for MVP (swap with Postgres/Redis later).

---

## Architecture (MVP)

**FastAPI** → **LangGraph** state machine:
1. `map_schema` (source → target fields via YAML mapping + DSPy Normalizer)
2. `validate` (target schema + per-channel requireds)
3. `plan_batches` (chunk items for rate-limit windows)
4. `throttle_and_upsert` (sliding-window limiter per channel)
5. `reconcile` (confirm + collect errors; in dry-run, only simulate)

**Configs**
- `configs/rate_limits.yaml` per channel
- `src/schema/mapping/{channel}.yaml` field mappings

**DSPy**
- `src/dspy/normalizer.py` defines a small program that polishes titles/attributes
- `data/training/normalizer_examples.jsonl` is the tiny gold set you can grow

**Hugging Face**
- Wrapper in `src/models/hf_models.py` (you can inject any pipeline/model you like)

---

## What to build next
- Replace channel stubs with real sandbox clients (Amazon/eBay).
- Persist jobs/results (SQLite → Postgres), add a background queue.
- Add human-in-the-loop review for validation failures.
- Track metrics (accept rate, first-try success, time-to-upsert).

---

## API

### POST `/translate/{channel}`
Translate and (optionally) upsert a catalog to a marketplace.

Query:
- `dry_run` (bool, default: `true`) — do everything except the final API call.

Body:
```json
{
  "catalog_path": "data/samples/catalog_sample.csv",
  "batch_size": 50
}
```

Response: JSON with per-step summaries and (if dry_run) a sample of translated listings.

---

## Dev notes
- Keep graphs pure and deterministic; push I/O to edges (channel clients, storage).
- Use `LangGraph` for explicit edges and replayability.
- Use `DSPy` to **learn** prompt/program parameters from your labeled rejects/accepts.
