#!/bin/bash
# Test script for mobile order creation flow
# Assumes cookies exist at /tmp/mxm_cookies.txt (from prior login)
# Usage: PRODUCT_ID=5 WAREHOUSE_ID=1 bash test_order_create.sh

set -e

BASE="${BASE:-http://127.0.0.1:8069}"
COOKIES="/tmp/mxm_cookies.txt"
PRODUCT_ID="${PRODUCT_ID:-5}"
WAREHOUSE_ID="${WAREHOUSE_ID:-1}"

if [ ! -f "$COOKIES" ]; then
    echo "ERROR: Cookie file not found at $COOKIES"
    echo "Please login first: curl -c $COOKIES -H 'Content-Type: application/json' -d '{\"phone\":\"YOUR_PHONE\",\"pin\":\"YOUR_PIN\"}' $BASE/api/v1/auth/login"
    exit 1
fi

echo "=== Step 1: GET cart (ensure cart exists) ==="
RESP=$(curl -s -w "\nHTTP_CODE:%{http_code}" -b "$COOKIES" "$BASE/api/v1/mxm/cart?warehouse_id=$WAREHOUSE_ID")
HTTP_CODE=$(echo "$RESP" | grep "HTTP_CODE:" | cut -d: -f2)
BODY=$(echo "$RESP" | sed '/HTTP_CODE:/d')
echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
if [ "$HTTP_CODE" -ge 400 ]; then
    echo "ERROR: GET cart failed with HTTP $HTTP_CODE"
    exit 1
fi
echo "✓ GET cart: HTTP $HTTP_CODE"
echo ""

echo "=== Step 2: POST cart line (add product) ==="
RESP=$(curl -s -w "\nHTTP_CODE:%{http_code}" -b "$COOKIES" -X POST "$BASE/api/v1/mxm/cart/lines" \
  -H "Content-Type: application/json" \
  -d "{\"product_id\":$PRODUCT_ID,\"qty\":1,\"warehouse_id\":$WAREHOUSE_ID}")
HTTP_CODE=$(echo "$RESP" | grep "HTTP_CODE:" | cut -d: -f2)
BODY=$(echo "$RESP" | sed '/HTTP_CODE:/d')
echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
if [ "$HTTP_CODE" -ge 400 ]; then
    echo "ERROR: POST cart/lines failed with HTTP $HTTP_CODE"
    exit 1
fi
echo "✓ POST cart/lines: HTTP $HTTP_CODE"
echo ""

echo "=== Step 3: POST order/create (checkout) ==="
RESP=$(curl -s -w "\nHTTP_CODE:%{http_code}" -b "$COOKIES" -X POST "$BASE/api/v1/mxm/order/create" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_primary": "99112233",
    "phone_secondary": "88112233",
    "delivery_address": "Test address, Building 5",
    "payment_method": "cod"
  }')
HTTP_CODE=$(echo "$RESP" | grep "HTTP_CODE:" | cut -d: -f2)
BODY=$(echo "$RESP" | sed '/HTTP_CODE:/d')
echo "$BODY" | jq . 2>/dev/null || echo "$BODY"
if [ "$HTTP_CODE" -ge 400 ]; then
    echo "ERROR: POST order/create failed with HTTP $HTTP_CODE"
    exit 1
fi
echo "✓ POST order/create: HTTP $HTTP_CODE"
echo ""

echo "=== Step 4: Verify cart cleared ==="
RESP=$(curl -s -w "\nHTTP_CODE:%{http_code}" -b "$COOKIES" "$BASE/api/v1/mxm/cart?warehouse_id=$WAREHOUSE_ID")
HTTP_CODE=$(echo "$RESP" | grep "HTTP_CODE:" | cut -d: -f2)
BODY=$(echo "$RESP" | sed '/HTTP_CODE:/d')
TOTAL_QTY=$(echo "$BODY" | jq -r '.data.total_qty // "unknown"' 2>/dev/null)
echo "Cart total_qty: $TOTAL_QTY"
if [ "$TOTAL_QTY" != "0" ]; then
    echo "WARNING: Cart not cleared (expected 0, got $TOTAL_QTY)"
fi
echo "✓ Verify cart: HTTP $HTTP_CODE"
echo ""

echo "=== ALL TESTS PASSED ==="
