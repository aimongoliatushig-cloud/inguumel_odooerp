#!/bin/bash
# Full verification: Bearer auth for ALL /api/v1/* (auth/me + mxm/*).
# Run after: sudo systemctl restart odoo19.service
# Optional: DEBUG_MOBILE_AUTH=1 in odoo19.service env to see logs in /opt/odoo/log/odoo19.log
set -e
BASE="${BASE:-http://127.0.0.1:8069}"
PHONE="${PHONE:-95909912}"
PIN="${PIN:-050206}"

echo "=== 1. Login ==="
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"$PHONE\",\"pin\":\"$PIN\"}")
TOKEN=$(echo "$RES" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('access_token','') or '')" 2>/dev/null || echo "")
if [ -z "$TOKEN" ]; then
  echo "[FAIL] No access_token. Check credentials and DB."
  exit 1
fi
echo "[OK] token len=${#TOKEN}"

echo ""
echo "=== 2. auth/me (expect 200) ==="
CODE=$(curl -s -o /tmp/me.json -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/auth/me")
echo "HTTP $CODE"
if [ "$CODE" != "200" ]; then echo "[FAIL] expected 200"; exit 1; fi
echo "[OK]"

echo ""
echo "=== 3. mxm/cart (expect 200) ==="
CODE=$(curl -s -o /tmp/cart.json -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/cart?warehouse_id=1")
echo "HTTP $CODE"
if [ "$CODE" != "200" ]; then echo "[FAIL] expected 200"; exit 1; fi
echo "[OK]"

echo ""
echo "=== 4. mxm/categories (expect 200) ==="
CODE=$(curl -s -o /tmp/cat.json -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/categories")
echo "HTTP $CODE"
if [ "$CODE" != "200" ]; then echo "[FAIL] expected 200"; exit 1; fi
echo "[OK]"

echo ""
echo "=== 5. mxm/products (expect 200) ==="
CODE=$(curl -s -o /tmp/products.json -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/products?warehouse_id=1&limit=5")
echo "HTTP $CODE"
if [ "$CODE" != "200" ]; then echo "[FAIL] expected 200"; exit 1; fi
echo "[OK]"

echo ""
echo "=== 6. Invalid token (expect 401 JSON) ==="
CODE=$(curl -s -o /tmp/unauth.json -w "%{http_code}" -H "Authorization: Bearer invalid-token-here" "$BASE/api/v1/auth/me")
echo "HTTP $CODE"
if [ "$CODE" != "401" ]; then echo "[FAIL] expected 401"; exit 1; fi
echo "[OK]"

echo ""
echo "=== All checks passed. Bearer auth is consistent for /api/v1/* ==="
