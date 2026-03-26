#!/usr/bin/env bash
# Verify delivery status API: GET /api/v1/orders/<id>/delivery and POST .../delivery/status
# Requires: curl, jq. Set BASE and use admin/staff credentials for POST.
set -e
BASE="${BASE:-http://127.0.0.1:8069}"
PHONE="${PHONE:-}"
PIN="${PIN:-}"
ORDER_ID="${ORDER_ID:-}"

echo "=== 1. /web/login (smoke) ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/web/login")
if [ "$CODE" != "200" ]; then
  echo "Expected 200, got $CODE"
  exit 1
fi
echo "OK $CODE"

echo ""
echo "=== 2. Login and get token ==="
if [ -z "$PHONE" ] || [ -z "$PIN" ]; then
  echo "Set PHONE and PIN for auth (e.g. admin user with mobile auth). Skipping authenticated tests."
  echo "Example: PHONE=95909912 PIN=050206 ./verify_delivery_api.sh"
  exit 0
fi
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"$PHONE\",\"pin\":\"$PIN\"}")
TOKEN=$(echo "$RES" | jq -r '.data.access_token // empty')
if [ -z "$TOKEN" ]; then
  echo "Login failed: $RES" | head -1
  exit 1
fi
echo "Token obtained"

echo ""
echo "=== 3. GET /api/v1/orders (list) to pick an order_id ==="
LIST=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders?limit=5")
ORDER_ID_FROM_LIST=$(echo "$LIST" | jq -r '.data[0].id // .data[0].order_id // empty')
if [ -n "$ORDER_ID" ]; then
  echo "Using ORDER_ID=$ORDER_ID"
elif [ -n "$ORDER_ID_FROM_LIST" ]; then
  ORDER_ID="$ORDER_ID_FROM_LIST"
  echo "Using order_id from list: $ORDER_ID"
else
  echo "No orders in list. Create an order first or set ORDER_ID=..."
  exit 1
fi

echo ""
echo "=== 4. GET /api/v1/orders/$ORDER_ID/delivery ==="
DELIVERY=$(curl -s -w "\nHTTP_CODE:%{http_code}" -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/orders/$ORDER_ID/delivery")
HTTP_CODE=$(echo "$DELIVERY" | grep "HTTP_CODE:" | cut -d: -f2)
BODY=$(echo "$DELIVERY" | sed '/HTTP_CODE:/d')
if [ "$HTTP_CODE" != "200" ]; then
  echo "Expected 200, got $HTTP_CODE"
  echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
  exit 1
fi
echo "$BODY" | jq .
echo "OK 200, timeline length: $(echo "$BODY" | jq '.data.timeline | length')"

echo ""
echo "=== 5. POST /api/v1/orders/$ORDER_ID/delivery/status (staff: set prepared) ==="
POST_RES=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$BASE/api/v1/orders/$ORDER_ID/delivery/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"prepared","note":"Test from script"}')
POST_CODE=$(echo "$POST_RES" | grep "HTTP_CODE:" | cut -d: -f2)
POST_BODY=$(echo "$POST_RES" | sed '/HTTP_CODE:/d')
if [ "$POST_CODE" != "200" ]; then
  echo "POST status returned $POST_CODE (may be 400 if transition not allowed)"
  echo "$POST_BODY" | jq . 2>/dev/null || echo "$POST_BODY"
else
  echo "$POST_BODY" | jq .
  echo "OK 200, current_status: $(echo "$POST_BODY" | jq -r '.data.current_status.code')"
fi

echo ""
echo "=== 6. GET delivery again (timeline should reflect change if POST succeeded) ==="
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/orders/$ORDER_ID/delivery" | jq '.data | {current_status, timeline: (.timeline | length)}'
echo "Done."
