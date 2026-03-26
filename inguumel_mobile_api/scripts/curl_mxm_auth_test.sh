#!/bin/bash
# MXM Auth/Cookie verification – run on server where Odoo is reachable.
# MUST: RN-ийн яг ашиглаж буй public BASE ашиглана (127.0.0.1 биш – cookie domain таарахгүй, RN Unauthorized үлдэнэ).
# Example: BASE="http://72.62.247.95:8069" PHONE="95909912" PIN="050206" bash curl_mxm_auth_test.sh
set -e
BASE="${BASE:-http://127.0.0.1:8069}"
PHONE="${PHONE:-95909912}"
PIN="${PIN:-050206}"
COOKIES="/tmp/mxm_cookies.txt"
rm -f "$COOKIES"

echo "=== A2 Login + Set-Cookie check (BASE=$BASE) ==="
RESP=$(curl -s -i -c "$COOKIES" \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"$PHONE\",\"pin\":\"$PIN\"}" \
  "$BASE/api/v1/auth/login")
echo "$RESP" | head -n 40
if echo "$RESP" | grep -qi "Set-Cookie:.*session_id"; then
  echo "[OK] Set-Cookie: session_id present"
else
  echo "[FAIL] Set-Cookie: session_id NOT found"
fi
STATUS=$(echo "$RESP" | grep -o "^HTTP/[0-9.]* [0-9]*" | awk '{print $2}')
echo "Login HTTP status: $STATUS"

echo ""
echo "=== Cookie file (tail) ==="
tail -n 20 "$COOKIES" 2>/dev/null || true

echo ""
echo "=== A3 auth/me ==="
curl -s -i -b "$COOKIES" "$BASE/api/v1/auth/me" | head -n 25

echo ""
echo "=== A3 categories ==="
curl -s -i -b "$COOKIES" "$BASE/api/v1/mxm/categories" | head -n 25

echo ""
echo "=== A3 products ==="
curl -s -i -b "$COOKIES" "$BASE/api/v1/mxm/products?warehouse_id=2&limit=5" | head -n 25

echo ""
echo "=== A4 cart GET ==="
curl -s -i -b "$COOKIES" "$BASE/api/v1/mxm/cart?warehouse_id=2" | head -n 25

echo ""
echo "=== A4 cart/lines POST ==="
curl -s -i -b "$COOKIES" -X POST "$BASE/api/v1/mxm/cart/lines" \
  -H "Content-Type: application/json" \
  -d '{"product_id":5,"qty":1,"warehouse_id":2}' | head -n 30
