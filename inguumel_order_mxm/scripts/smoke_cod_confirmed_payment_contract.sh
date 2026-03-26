#!/usr/bin/env bash
# Smoke test: after COD confirm, driver orders list and detail must show PAID consistently.
# Usage: BASE=http://127.0.0.1:8069 DRIVER_PHONE=... DRIVER_PIN=... ORDER_ID=... ./scripts/smoke_cod_confirmed_payment_contract.sh
# 1) Ensure order is COD and not yet confirmed; 2) Call POST .../cod/confirm; 3) GET detail and list; 4) Assert paid/PAID/Төлөгдсөн.
set -e
BASE="${BASE:-http://127.0.0.1:8069}"
ORDER_ID="${ORDER_ID:-}"
DRIVER_PHONE="${DRIVER_PHONE:-}"
DRIVER_PIN="${DRIVER_PIN:-}"

if [ -z "$ORDER_ID" ] || [ -z "$DRIVER_PHONE" ] || [ -z "$DRIVER_PIN" ]; then
  echo "Usage: ORDER_ID=<id> DRIVER_PHONE=<phone> DRIVER_PIN=<pin> $0"
  echo "Optional: BASE=http://127.0.0.1:8069"
  exit 1
fi

echo "=== 1. Driver login ==="
LOGIN=$(curl -s -X POST "$BASE/api/v1/driver/auth/login" -H "Content-Type: application/json" -H "X-App: driver" \
  -d "{\"phone\":\"$DRIVER_PHONE\",\"pin\":\"$DRIVER_PIN\"}")
TOKEN=$(echo "$LOGIN" | jq -r '.data.access_token // empty')
if [ -z "$TOKEN" ]; then
  echo "Login failed: $LOGIN" | head -1
  exit 1
fi
echo "OK (token present)"

echo ""
echo "=== 2. COD confirm (idempotent if already confirmed) ==="
CONFIRM=$(curl -s -X POST "$BASE/api/v1/driver/orders/$ORDER_ID/cod/confirm" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}')
echo "$CONFIRM" | jq -c '{ success, message, data: .data | { order_id, x_cod_confirmed, x_cod_amount } }'
if [ "$(echo "$CONFIRM" | jq -r '.success')" != "true" ]; then
  echo "COD confirm failed (order may not be COD or not in scope): $CONFIRM" | head -1
  exit 1
fi
echo "OK"

echo ""
echo "=== 3. GET /api/v1/driver/orders/{id} – must show PAID / Төлөгдсөн ==="
DETAIL=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/orders/$ORDER_ID")
echo "$DETAIL" | jq -c '.data | {
  payment_state_code,
  payment_state_label_mn,
  is_paid,
  payment_status,
  payment_status_label_mn,
  "payment.paid": .payment.paid,
  "payment.payment_status": .payment.payment_status
}'
CODE=$(echo "$DETAIL" | jq -r '.data.payment_state_code')
PAID=$(echo "$DETAIL" | jq -r '.data.is_paid')
LABEL=$(echo "$DETAIL" | jq -r '.data.payment_state_label_mn')
if [ "$CODE" != "PAID" ] || [ "$PAID" != "true" ] || [ "$LABEL" != "Төлөгдсөн" ]; then
  echo "FAIL: expected payment_state_code=PAID, is_paid=true, payment_state_label_mn=Төлөгдсөн"
  exit 1
fi
echo "OK – detail shows PAID / Төлөгдсөн"

echo ""
echo "=== 4. GET /api/v1/driver/orders (list) – same order must show Төлөгдсөн ==="
LIST=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/orders?limit=50")
ITEM=$(echo "$LIST" | jq -c ".data[]? | select(.order_id == $ORDER_ID or .id == $ORDER_ID) | { order_id: (.order_id // .id), payment_state_code, payment_state_label_mn, is_paid }")
if [ -z "$ITEM" ]; then
  echo "Order $ORDER_ID not found in list (or key is order_id/id)"
  echo "$LIST" | jq -c '.data[0:2]? | .[] | { order_id: (.order_id // .id), payment_state_label_mn }'
else
  echo "$ITEM"
  LCODE=$(echo "$ITEM" | jq -r '.payment_state_code')
  LPAID=$(echo "$ITEM" | jq -r '.is_paid')
  LLABEL=$(echo "$ITEM" | jq -r '.payment_state_label_mn')
  if [ "$LCODE" != "PAID" ] || [ "$LPAID" != "true" ] || [ "$LLABEL" != "Төлөгдсөн" ]; then
    echo "FAIL: list item expected payment_state_code=PAID, is_paid=true, payment_state_label_mn=Төлөгдсөн"
    exit 1
  fi
  echo "OK – list shows Төлөгдсөн for order $ORDER_ID"
fi

echo ""
echo "Done. COD confirmed order shows PAID consistently in list and detail."
