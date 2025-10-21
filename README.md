# market-translator

Translate your internal product catalog into marketplace-ready payloads and safely upsert them to channels like **Amazon** and **eBay**.  
Built with **FastAPI**, **LangGraph**, **DSPy (local)**, and optional **Hugging Face** helpers.

---

## Highlights

- 🔁 **Pipeline (LangGraph):** map → validate → plan batches → upsert (rate-limit hook) → reconcile  
- ✅ **Validation**
  - Base required-field checks (per channel)
  - **Amazon:** optional, real **Product Type Definitions (PTD)** JSON Schema validation (no SigV4; **LWA only**)
  - **eBay:** category **aspects** check via Metadata/Taxonomy
- 🚦 **Dry-run & preview:** `POST /translate/{channel}?dry_run=true` summarizes mapped/valid items
- 🧪 **Sandboxes** supported for Amazon & eBay
- 🧩 **Pluggable channels:** shared interface in `src/channels/base.py`

---

## Stack

- Python **3.11** (required)
- FastAPI + Uvicorn
- LangGraph
- httpx, jsonschema  
- *(Optional)* DSPy local helpers, Hugging Face utils

---

## Quickstart

### 1) Python & venv

```bash
# Ensure Python 3.11 (pyenv recommended)
pyenv local 3.11.9

# Create and activate venv
python -m venv .venv
source .venv/bin/activate

# Upgrade pip and install
python -m pip install -U pip
pip install -e .
```

### 2) Environment

```bash
cp .env.example .env
```

#### Amazon (sandbox or prod, LWA only):

```dotenv
# LWA (Login with Amazon)
LWA_CLIENT_ID="amzn1.application-oa2-client.xxxxx"
LWA_CLIENT_SECRET="xxxxx"
LWA_REFRESH_TOKEN="Atzr|xxxxx"

# SP-API host (sandbox or prod region)
SPAPI_HOST="https://sandbox.sellingpartnerapi-na.amazon.com"  # prod: https://sellingpartnerapi-na.amazon.com

# Your seller info
SELLER_ID="A2XXXXXXXXXXXXX"
MARKETPLACE_IDS="ATVPDKIKX0DER"    # US; comma-list OK

# Optional
SPAPI_USER_AGENT="market-translator/0.1 (Language=Python)"
SPAPI_ISSUE_LOCALE="en_US"
SPAPI_SCHEMA_VALIDATE=1            # enable PTD JSON Schema check
```

#### eBay (sandbox or prod):

```dotenv
EBAY_BASE_URL="https://api.sandbox.ebay.com"      # prod: https://api.ebay.com
EBAY_CLIENT_ID="..."
EBAY_CLIENT_SECRET="..."
EBAY_REFRESH_TOKEN="..."                           # OAuth Refresh Token
EBAY_MARKETPLACE_ID="EBAY_US"                      # e.g., EBAY_US, EBAY_GB

# Optional policy overrides (or the client auto-picks first)
# EBAY_PAYMENT_POLICY_ID=""
# EBAY_RETURN_POLICY_ID=""
# EBAY_FULFILLMENT_POLICY_ID=""

# Optional default category
# EBAY_DEFAULT_CATEGORY_ID="9344"
```

##### Load env in your shell (zsh):

```bash
set -a; source .env; set +a
```

### 3) Run the API

```bash
python -m uvicorn src.app.main:app --reload
# open http://127.0.0.1:8000/docs
```

---

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Basic health check (current router exposes `/health`). |
| POST | `/translate/{channel}?dry_run=true\|false` | Run the pipeline for `amazon` or `ebay`. With `dry_run=true`, returns counts + preview. |
| POST   | `/review/{channel}`                | Return rejects + error codes to drive a fix-up UI (filter/sort/paging supported). |
| POST | `/ebay/validate` | Validate a single eBay payload (title/brand/price + optional category aspects). |
| POST | `/ebay/upsert/{sku}?mode=DRAFT\|LIVE` | Create/replace Inventory Item → Offer; publish when `mode=LIVE`. |


### Translate request

`POST /translate/amazon?dry_run=true`

```json
{
  "catalog_path": "data/samples/catalog.csv",
  "batch_size": 50,
  "extra": {
    "amazon_product_type": "PRODUCT",
    "amazon_requirements": "LISTING",
    "amazon_enforced": "ENFORCED",
    "amazon_locale": "en_US"
  }
}
```

#### Response (example):

```json 
{
  "channel": "amazon",
  "counts": {
    "input_items": 3,
    "mapped": 3,
    "valid": 3,
    "batches": 1,
    "upserted": 3,
    "errors": 0
  },
  "preview_mapped": [ ... ],
  "errors": []
}
```

---

## Data inputs

### Catalog CSV

The loader accepts columns like:
- `id` / `sku` / `ID`
- `title`, `description`
- any other columns are placed into `attributes`

#### Example `data/samples/catalog.csv`:

```csv
id,title,description,brand,price,color,size
SKU-001,Premium Cotton T-Shirt,Soft cotton tee for everyday wear,Acme,19.99,Black,M
SKU-002,Wireless Mouse,Ergonomic 2.4G mouse with silent clicks,TechCo,24.50,Gray,
SKU-003,Stainless Water Bottle,Insulated 500ml bottle,Hydra,14.00,Blue,500ml
```

---

## Channel behavior

### Amazon

- **LWA only** (no SigV4 required for PTD & many endpoints per Amazon’s update).
- Optional **PTD JSON Schema validation** before you call Listings:
  - Fetches product type schema via **Product Type Definitions API**
  - Validates your `{ productType, attributes }` using `jsonschema` (standard JSON Schema 2019/2020 rules)
  - Amazon’s **custom vocabulary** is ignored by default (you still get strong checks: type/required/enum/pattern/etc.)

Toggle with:

```dotenv
SPAPI_SCHEMA_VALIDATE=1   # enable
```

#### Script to discover your marketplace(s):

```bash
./scripts/spapi_marketplaces.sh
```

The script exchanges LWA refresh → access token, then calls:

```bash
GET /sellers/v1/marketplaceParticipations on $SPAPI_HOST
```

### eBay

- OAuth2 app token for taxonomy/metadata, user token (refresh) for inventory/offer.
- validate_listing:
  - Cheap guards for title, price, brand
  - If categoryId provided, fetch required aspects and check presence
- upsert_listing:
  - InventoryItem → Offer; publish only when mode=LIVE
  - Payment/return/fulfillment policy IDs are auto-discovered if not set

#### Swagger helpers:

- ``POST /ebay/validate``
- ``POST /ebay/upsert/{sku}?mode=DRAFT|LIVE``

---

## Project layout

```pgsql
src/
  app/
    main.py
    routers/
      translate.py
      health.py
      metrics.py
      ebay.py            
  channels/
    base.py
    amazon.py
    ebay.py             
  models/
    hf_models.py
    ptd_validator.py
  pipeline/
    graph.py
    state.py
    nodes/
      map_schema.py
      validate.py
      plan_batches.py
      upsert.py
      reconcile.py
  schema/
    mapping/
      amazon.yaml
      loader.py
  dspylocal/
    normalizer.py
```

---

## Testing

```bash
# run all tests
pytest -q

# or just eBay integration route tests
pytest -q tests/integration/test_ebay_routes.py
```

---

## Development notes

- Imports / package layout: run as a package. If you see
`attempted relative import beyond top-level package`, start with:

  ```bash
  python -m uvicorn src.app.main:app --reload
  ```

- Quoting `.env`: refresh tokens contain `|` and user-agent has parentheses; wrap values in quotes.

---

## Scripts

- `scripts/spapi_marketplaces.sh` — Get your Amazon marketplace IDs for your account (uses `.env` LWA creds).
  ```bash
  chmod +x scripts/spapi_marketplaces.sh
  set -a; source .env; set +a
  ./scripts/spapi_marketplaces.sh
  ```

---

## Roadmap

- `/review` endpoint that returns rejects with compact error codes (for a fix-up UI)

- Amazon Listings Items `mode=VALIDATION_PREVIEW` path

- eBay policy caching + category helper

- More channels (Walmart, TikTok Shop…)

---

## License

MIT (see `LICENSE`).
