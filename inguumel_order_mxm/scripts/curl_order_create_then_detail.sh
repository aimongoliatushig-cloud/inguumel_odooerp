#!/bin/bash
# Create order → 200, then immediately fetch order detail → 200 (Bearer auth).
# Demonstrates deterministic response (id, name, status) and immediate navigation.
# Usage: BASE="http://127.0.0.1:8069" bash scripts/curl_order_create_then_detail.sh

set -e
BASE="${BASE:-http://127.0.0.1:8069}"
PHONE="${PHONE:-95909912}"
PIN="${PIN:-050206}"
WAREHOUSE_ID="${WAREHOUSE_ID:-1}"

echo "=== 1. Login (Bearer token) ==="
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"$PHONE\",\"pin\":\"$PIN\"}")
TOKEN=$(echo "$RES" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('access_token','') or '')" 2>/dev/null || echo "")
if [ -z "$TOKEN" ]; then
  echo "[FAIL] No access_token. Check credentials."
  exit 1
fi
echo "[OK] token len=${#TOKEN}"
echo ""

echo "=== 2. Add item to cart ==="
CART=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/cart?warehouse_id=$WAREHOUSE_ID")
# Add a line (product_id and qty depend on your DB)
ADD=$(curl -s -w "\n%{http_code}" -X POST "$BASE/api/v1/mxm/cart/lines" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"product_id\":1,\"qty\":1,\"warehouse_id\":$WAREHOUSE_ID}")
HTTP_ADD=$(echo "$ADD" | tail -n1)
if [ "$HTTP_ADD" != "200" ]; then
  echo "[SKIP] POST cart/lines returned $HTTP_ADD (no product_id=1?). Trying order/create anyway."
fi
echo ""

echo "=== 3. POST order/create (expect 200, data.id + data.name + data.status) ==="
CREATE=$(curl -s -w "\n%{http_code}" -X POST "$BASE/api/v1/mxm/order/create?warehouse_id=$WAREHOUSE_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"phone_primary\":\"$PHONE\",\"delivery_address\":\"Test address\",\"payment_method\":\"cod\"}")
BODY=$(echo "$CREATE" | sed '$d')
CODE=$(echo "$CREATE" | tail -n1)
echo "HTTP $CODE"
echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
if [ "$CODE" != "200" ]; then
  echo "[FAIL] Expected 200, got $CODE"
  exit 1
fi
ORDER_ID=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('id') or d.get('data',{}).get('order_id') or '')" 2>/dev/null || echo "")
ORDER_NAME=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('name') or d.get('data',{}).get('order_number') or '')" 2>/dev/null || echo "")
STATUS=$(echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('status') or '')" 2>/dev/null || echo "")
if [ -z "$ORDER_ID" ]; then
  echo "[FAIL] No order id in response"
  exit 1
fi
echo "[OK] order_id=$ORDER_ID name=$ORDER_NAME status=$STATUS"
echo ""

echo "=== 4. GET order detail (expect 200, readable immediately) ==="
DETAIL=$(curl -s -w "\n%{http_code}" -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders/$ORDER_ID")
BODY_D=$(echo "$DETAIL" | sed '$d')
CODE_D=$(echo "$DETAIL" | tail -n1)
echo "HTTP $CODE_D"
echo "$BODY_D" | python3 -m json.tool 2>/dev/null || echo "$BODY_D"
if [ "$CODE_D" != "200" ]; then
  echo "[FAIL] Expected 200 for order detail, got $CODE_D"
  exit 1
fi
echo "[OK] Order detail readable immediately after creation"
echo ""
echo "=== All passed: create → 200, detail → 200 (direct navigation) ==="
