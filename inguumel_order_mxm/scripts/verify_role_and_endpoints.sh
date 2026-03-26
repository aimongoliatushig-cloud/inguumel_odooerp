#!/usr/bin/env bash
# Verify role mapping and correct endpoints (Driver/Cashier buttons).
# Usage: BASE=http://localhost:8069 ./verify_role_and_endpoints.sh

set -e
BASE="${BASE:-http://localhost:8069}"

echo "=== 1. Driver (00000000) login -> role must be 'driver' ==="
DRIVER_ROLE=$(curl -s -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" \
  -d '{"phone":"00000000","pin":"123123"}' | jq -r '.data.role // empty')
echo "Driver role: $DRIVER_ROLE"
if [ "$DRIVER_ROLE" = "driver" ]; then
  echo "OK: Driver role is driver"
else
  echo "FAIL: Expected role=driver, got role=$DRIVER_ROLE (assign user to Inguumel Order / Driver and set warehouses)"
fi

echo ""
echo "=== 2. Cashier (00000001) login -> role must be 'cashier' ==="
CASHIER_ROLE=$(curl -s -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" \
  -d '{"phone":"00000001","pin":"123123"}' | jq -r '.data.role // empty')
echo "Cashier role: $CASHIER_ROLE"
if [ "$CASHIER_ROLE" = "cashier" ]; then
  echo "OK: Cashier role is cashier"
else
  echo "FAIL: Expected role=cashier, got role=$CASHIER_ROLE (assign user to Inguumel Order / Cash Confirm (Cashier))"
fi

echo ""
echo "=== 3. Order detail: GET /api/v1/mxm/orders/<id> (not /api/v1/orders/<id>) ==="
CASHIER_TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" \
  -d '{"phone":"00000001","pin":"123123"}' | jq -r '.data.access_token // empty')
ORDER_ID="${ORDER_ID:-63}"
if [ -n "$CASHIER_TOKEN" ]; then
  MXM_HTTP=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $CASHIER_TOKEN" "$BASE/api/v1/mxm/orders/$ORDER_ID")
  OLD_HTTP=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $CASHIER_TOKEN" "$BASE/api/v1/orders/$ORDER_ID")
  echo "GET /api/v1/mxm/orders/$ORDER_ID -> $MXM_HTTP (expect 200)"
  echo "GET /api/v1/orders/$ORDER_ID -> $OLD_HTTP (expect 404 - do not use in RN)"
  [ "$MXM_HTTP" = "200" ] && echo "OK: mxm/orders works"
  [ "$OLD_HTTP" = "404" ] && echo "OK: old route 404 so RN must use mxm/orders"
fi

echo ""
echo "=== 4. Driver order detail: GET /api/v1/driver/orders/<id> ==="
DRIVER_TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" \
  -d '{"phone":"00000000","pin":"123123"}' | jq -r '.data.access_token // empty')
if [ -n "$DRIVER_TOKEN" ]; then
  DRIVER_ORDER_HTTP=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $DRIVER_TOKEN" "$BASE/api/v1/driver/orders/$ORDER_ID")
  echo "GET /api/v1/driver/orders/$ORDER_ID -> $DRIVER_ORDER_HTTP (expect 200 if order in scope)"
  [ "$DRIVER_ORDER_HTTP" = "200" ] && echo "OK: driver/orders works"
fi

echo ""
echo "=== 5. Cash confirm: POST /api/v1/orders/<id>/cash-confirm (cashier only) ==="
if [ -n "$CASHIER_TOKEN" ]; then
  curl -s -X POST "$BASE/api/v1/orders/$ORDER_ID/cash-confirm" \
    -H "Authorization: Bearer $CASHIER_TOKEN" -H "Content-Type: application/json" -d '{}' | jq -c '{ success, message, data: { order_id: .data.order_id, already_confirmed: .data.already_confirmed } }'
fi

echo ""
echo "=== 6. Driver delivery status: POST /api/v1/driver/orders/<id>/delivery/status ==="
if [ -n "$DRIVER_TOKEN" ]; then
  curl -s -X POST "$BASE/api/v1/driver/orders/$ORDER_ID/delivery/status" \
    -H "Authorization: Bearer $DRIVER_TOKEN" -H "Content-Type: application/json" \
    -d '{"status":"preparing","note":"Test"}' | jq -c '{ success, code, data: .data.current_status.code }'
fi

echo ""
echo "Done. Assign Driver/Cash Confirm groups in Odoo if roles were not driver/cashier."
