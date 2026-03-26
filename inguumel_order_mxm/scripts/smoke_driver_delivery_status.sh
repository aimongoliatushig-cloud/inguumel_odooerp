#!/usr/bin/env bash
# Smoke test: login -> get order_id -> POST delivery/status status=preparing -> expect success true.
# Use when order has picking; for orders without picking you may get NO_DELIVERY_PICKING (expected).
# Usage: BASE_URL=http://localhost:8069 DRIVER_LOGIN=driver1 DRIVER_PASSWORD=... [ORDER_ID=55] ./scripts/smoke_driver_delivery_status.sh

set -e
BASE="${BASE_URL:-http://localhost:8069}"
DRIVER_LOGIN="${DRIVER_LOGIN:-driver1}"
DRIVER_PASSWORD="${DRIVER_PASSWORD:-123123}"

echo "=== Smoke: driver delivery status (preparing) ==="
RES=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$BASE/api/v1/driver/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"login\":\"$DRIVER_LOGIN\",\"password\":\"$DRIVER_PASSWORD\"}")
BODY=$(echo "$RES" | sed '$d')
TOKEN=$(echo "$BODY" | jq -r '.data.access_token // empty')
[ -z "$TOKEN" ] && { echo "Login failed"; exit 1; }

if [ -z "$ORDER_ID" ]; then
  ORDER_ID=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/orders?limit=1" | jq -r '.data[0].order_id // empty')
  [ -z "$ORDER_ID" ] && { echo "No orders in scope"; exit 1; }
fi

echo "POST .../orders/$ORDER_ID/delivery/status {\"status\":\"preparing\"}"
RES=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$BASE/api/v1/driver/orders/$ORDER_ID/delivery/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"preparing","note":"Smoke test"}')
HTTP_CODE=$(echo "$RES" | tail -n1)
BODY=$(echo "$RES" | sed '$d')
SUCCESS=$(echo "$BODY" | jq -r '.success')
CODE=$(echo "$BODY" | jq -r '.code')
REQUEST_ID=$(echo "$BODY" | jq -r '.request_id')

echo "HTTP $HTTP_CODE success=$SUCCESS code=$CODE request_id=$REQUEST_ID"
echo "$BODY" | jq .

if [ "$SUCCESS" != "true" ]; then
  echo "Smoke FAIL: expected success=true (request_id=$REQUEST_ID for logs)"
  exit 1
fi
echo "Smoke PASS: success=true"
