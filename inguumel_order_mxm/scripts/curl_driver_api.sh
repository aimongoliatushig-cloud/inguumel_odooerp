#!/usr/bin/env bash
# Drive App API – 6 curl examples (login, me, orders list, order detail, delivery get, delivery update)
# Set BASE to production or local; ensure a driver user exists (res.users with x_warehouse_ids).

set -e
BASE="${BASE_URL:-http://localhost:8069}"

echo "=== 1. POST /api/v1/driver/auth/login ==="
RES=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$BASE/api/v1/driver/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"login":"driver1","password":"123123"}')
HTTP_CODE=$(echo "$RES" | tail -n1)
BODY=$(echo "$RES" | sed '$d')
echo "HTTP $HTTP_CODE"
echo "$BODY" | jq .
TOKEN=$(echo "$BODY" | jq -r '.data.access_token // empty')
if [ -z "$TOKEN" ]; then
  echo "No access_token – fix login/password or assign x_warehouse_ids to user. Exit."
  exit 1
fi

echo ""
echo "=== 2. GET /api/v1/driver/auth/me ==="
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/auth/me" | jq .

echo ""
echo "=== 3. GET /api/v1/driver/orders?limit=50&offset=0 ==="
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/orders?limit=50&offset=0" | jq .
ORDER_ID=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/orders?limit=1" | jq -r '.data[0].order_id // empty')
if [ -z "$ORDER_ID" ]; then
  echo "No orders in scope – use a driver user with orders in assigned warehouses."
  ORDER_ID=1
fi

echo ""
echo "=== 4. GET /api/v1/driver/orders/$ORDER_ID ==="
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/orders/$ORDER_ID" | jq .

echo ""
echo "=== 5. GET /api/v1/driver/orders/$ORDER_ID/delivery ==="
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/orders/$ORDER_ID/delivery" | jq .

echo ""
echo "=== 6. POST /api/v1/driver/orders/$ORDER_ID/delivery/status (e.g. preparing) ==="
curl -s -X POST "$BASE/api/v1/driver/orders/$ORDER_ID/delivery/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"preparing","note":"Driver app test"}' | jq .

echo ""
echo "=== 7. POST .../delivery/status with delivered (validates picking, On Hand decreases) ==="
echo "Body accepts 'status' or 'code'. Same response shape as GET .../delivery."
curl -s -X POST "$BASE/api/v1/driver/orders/$ORDER_ID/delivery/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"delivered","note":"Driver delivered"}' | jq .

echo ""
echo "Done. request_id is in every response for tracing."
