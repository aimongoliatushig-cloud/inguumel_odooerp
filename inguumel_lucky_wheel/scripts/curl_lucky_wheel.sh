#!/usr/bin/env bash
# Smoke test: Lucky Wheel API (eligibility, spin, redeem)
# Usage: BASE=http://localhost:8069 TOKEN=<bearer> WAREHOUSE_ID=1 ./scripts/curl_lucky_wheel.sh
set -e
BASE="${BASE:-http://127.0.0.1:8069}"
TOKEN="${TOKEN:-}"
WID="${WAREHOUSE_ID:-1}"

echo "=== Lucky Wheel smoke test ==="
echo "BASE=$BASE WAREHOUSE_ID=$WID"

[ -z "$TOKEN" ] && echo "Set TOKEN (Bearer from auth/login)" && exit 1

# 1) Eligibility
echo ""
echo "GET /api/v1/lucky-wheel/eligibility?warehouse_id=$WID"
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/lucky-wheel/eligibility?warehouse_id=$WID" | jq .

# 2) Spin (requires Idempotency-Key)
KEY="smoke-$(date +%s)-$$"
echo ""
echo "POST /api/v1/lucky-wheel/spin (Idempotency-Key: $KEY)"
curl -s -X POST "$BASE/api/v1/lucky-wheel/spin" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $KEY" \
  -d "{\"warehouse_id\": $WID}" | jq .

echo ""
echo "=== Done ==="
