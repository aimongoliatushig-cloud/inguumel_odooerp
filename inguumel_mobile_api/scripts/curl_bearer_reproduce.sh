#!/bin/bash
# Reproduce Bearer auth: auth/me and mxm/cart must both return 200 with Bearer token.
# After changing inguumel_mobile_api/models/ir_http.py you MUST restart Odoo for Python changes to apply.
# Optional: DEBUG_MOBILE_AUTH=1 odoo [...] to see per-request auth logs.
# Then: BASE="http://127.0.0.1:8069" bash scripts/curl_bearer_reproduce.sh
set -e
BASE="${BASE:-http://127.0.0.1:8069}"
PHONE="${PHONE:-95909912}"
PIN="${PIN:-050206}"

echo "=== 1. Login to get token ==="
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"$PHONE\",\"pin\":\"$PIN\"}")
echo "$RES" | head -c 500
echo ""

TOKEN=$(echo "$RES" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('access_token','') or '')" 2>/dev/null || echo "")

if [ -z "$TOKEN" ]; then
  echo "[FAIL] No access_token in login response. Check credentials and DB."
  exit 1
fi
echo "[OK] Got token (len=${#TOKEN})"

echo ""
echo "=== 2. auth/me with Bearer ==="
curl -s -i -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/auth/me" | head -n 25

echo ""
echo "=== 3. mxm/cart with Bearer ==="
curl -s -i -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/cart?warehouse_id=1" | head -n 25
