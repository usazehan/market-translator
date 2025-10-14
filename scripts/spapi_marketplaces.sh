#!/usr/bin/env bash
set -euo pipefail

# Requires: LWA_CLIENT_ID, LWA_CLIENT_SECRET, LWA_REFRESH_TOKEN
# Optional: SPAPI_HOST (defaults to sandbox NA)

: "${LWA_CLIENT_ID:?Missing LWA_CLIENT_ID}"
: "${LWA_CLIENT_SECRET:?Missing LWA_CLIENT_SECRET}"
: "${LWA_REFRESH_TOKEN:?Missing LWA_REFRESH_TOKEN}"

SPAPI_HOST="${SPAPI_HOST:-https://sandbox.sellingpartnerapi-na.amazon.com}"

# 1) Get an LWA access token
ACCESS_TOKEN="$(
  curl -sS https://api.amazon.com/auth/o2/token \
    -d grant_type=refresh_token \
    -d "refresh_token=${LWA_REFRESH_TOKEN}" \
    -d "client_id=${LWA_CLIENT_ID}" \
    -d "client_secret=${LWA_CLIENT_SECRET}" \
  | jq -r '.access_token'
)"

echo "LWA access token acquired (truncated): ${ACCESS_TOKEN:0:16}..."

# 2) Call Sellers API to list marketplace participations
curl -sS "${SPAPI_HOST}/sellers/v1/marketplaceParticipations" \
  -H "x-amz-access-token: ${ACCESS_TOKEN}" \
  -H "accept: application/json" \
| jq .
