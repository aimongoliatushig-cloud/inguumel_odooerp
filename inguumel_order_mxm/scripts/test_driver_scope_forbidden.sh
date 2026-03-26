#!/usr/bin/env bash
# Test: order exists but warehouse mismatch must return 403 FORBIDDEN, not 404 NOT_FOUND.
# Usage: DRIVER_PASSWORD=... ORDER_ID_OTHER_WAREHOUSE=<id> ./test_driver_scope_forbidden.sh
set -e
BASE="${BASE_URL:-http://localhost:8069}"
LOGIN="${DRIVER_LOGIN:-driver1}"
OID="${ORDER_ID_OTHER_WAREHOUSE:-}"
curl -s -X POST "$BASE/api/v1/driver/auth/login" -H "Content-Type: application/json" -d "{\"login\":\"$LOGIN\",\"password\":\"$DRIVER_PASSWORD\"}" | jq -r '.data.access_token' > /tmp/tok
TOKEN=$(cat /tmp/tok)
[ -z "$TOKEN" ] && exit 1
[ -z "$OID" ] && echo "Set ORDER_ID_OTHER_WAREHOUSE" && exit 0
R=$(curl -s -w "%{http_code}" -o /tmp/body -X POST "$BASE/api/v1/driver/orders/$OID/delivery/status" -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"status":"preparing"}')
CODE=$(jq -r '.code' /tmp/body)
[ "$CODE" = "NOT_FOUND" ] && echo "FAIL: got NOT_FOUND" && exit 1
[ "$R" != "403" ] || [ "$CODE" != "FORBIDDEN" ] && echo "FAIL: want 403 FORBIDDEN" && exit 1
echo "PASS: 403 FORBIDDEN"
