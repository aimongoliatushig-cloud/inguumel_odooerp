#!/bin/bash
# Proof: order detail response contains order_state_label_mn, payment_method_label_mn, payment_status_label_mn.
# Usage: BASE="http://127.0.0.1:8069" bash scripts/curl_order_detail_label_mn.sh

set -e
BASE="${BASE:-http://127.0.0.1:8069}"
PHONE="${PHONE:-95909912}"
PIN="${PIN:-050206}"

echo "=== 1. Login (Bearer) ==="
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"$PHONE\",\"pin\":\"$PIN\"}")
TOKEN=$(echo "$RES" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('access_token','') or '')" 2>/dev/null || echo "")
if [ -z "$TOKEN" ]; then
  echo "[FAIL] No access_token."
  exit 1
fi
echo "[OK] token obtained"
echo ""

echo "=== 2. GET /api/v1/mxm/orders (list) ==="
LIST=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders")
echo "$LIST" | python3 -m json.tool 2>/dev/null | head -80
ORDER_ID=$(echo "$LIST" | python3 -c "
import sys, json
d = json.load(sys.stdin)
items = d.get('data') or []
if isinstance(items, dict) and 'items' in items:
    items = items['items']
if not items:
    sys.exit(1)
print(items[0].get('order_id') or items[0].get('id') or '')
" 2>/dev/null || echo "")
if [ -z "$ORDER_ID" ]; then
  echo "[SKIP] No orders in list. Create an order first, then re-run."
  exit 0
fi
echo "[OK] first order_id=$ORDER_ID"
echo ""

echo "=== 3. GET /api/v1/mxm/orders/$ORDER_ID (detail) – check *_label_mn ==="
DETAIL=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders/$ORDER_ID")
echo "$DETAIL" | python3 -m json.tool 2>/dev/null || echo "$DETAIL"

# Stable contract: order_state_code, payment_*_code, *_label_mn, is_paid
MISSING=""
echo "$DETAIL" | python3 -c "
import sys, json
d = json.load(sys.stdin)
data = d.get('data') or {}
required = [
    'order_state_code', 'order_state_label_mn',
    'payment_method_code', 'payment_method_label_mn',
    'payment_state_code', 'payment_state_label_mn',
    'is_paid',
]
for key in required:
    if key not in data:
        print('MISSING:', key)
        sys.exit(1)
# Backward compat
for key in ['order_state', 'payment_method', 'payment_status']:
    if key not in data:
        print('MISSING (backward):', key)
        sys.exit(1)
print('OK: order_state_code=%r payment_method_code=%r payment_state_code=%r is_paid=%s' % (
    data.get('order_state_code'),
    data.get('payment_method_code'),
    data.get('payment_state_code'),
    data.get('is_paid'),
))
" || MISSING=1
if [ -n "$MISSING" ]; then
  echo "[FAIL] Detail response missing one or more stable contract fields."
  exit 1
fi
echo ""
echo "=== Proof: GET /api/v1/mxm/orders/<id> returns order_state_code, payment_method_code, payment_state_code, *_label_mn, is_paid ==="
