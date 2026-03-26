#!/usr/bin/env bash
set -e

BASE="http://127.0.0.1:8069"
DB="InguumelStage"
WAREHOUSE_ID=1
PRODUCT_ID=3714
QTY=1
PHONE="95909912"
PIN="050206"

echo "== LOGIN =="
TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"$PHONE\",\"pin\":\"$PIN\"}" | jq -r '.data.access_token')

if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
  echo "LOGIN FAILED"; exit 1
fi
echo "TOKEN OK"

echo
echo "== CREATE MXM ORDER =="
RES=$(curl -s -X POST "$BASE/api/v1/mxm/orders" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"warehouse_id\":$WAREHOUSE_ID,\"items\":[{\"product_id\":$PRODUCT_ID,\"qty\":$QTY}]}")

echo "$RES" | jq .

RID=$(echo "$RES" | jq -r '.request_id // empty')
SUCCESS=$(echo "$RES" | jq -r '.success')

echo
echo "RID=$RID"
echo "SUCCESS=$SUCCESS"

echo
echo "== MXM LOG CHECK (last 5 min) =="
sudo journalctl -u odoo19 --since "5 minutes ago" --no-pager \
 | egrep "$RID|\[MXM_RULE\]|\[MXM_ORDER_DIAG\]|\[MXM_LAUNCH_STOCK_RULE\]" \
 | tail -n 300

if [ "$SUCCESS" != "true" ]; then
  echo
  echo "❌ ORDER FAILED (expected SUCCESS=true)"
  exit 0
fi

echo
echo "== CHECK OUTGOING PICKING (DB) =="
# API returns order_number (order.name), used as stock_picking.origin
ORDER_NAME=$(echo "$RES" | jq -r '.data.order_number // empty')

sudo -u odoo psql -d "$DB" -c "
SELECT sp.id AS picking_id,
       sp.name,
       pt.code AS picking_type,
       dest.complete_name AS dest_location
FROM stock_picking sp
JOIN stock_picking_type pt ON pt.id=sp.picking_type_id
JOIN stock_location dest ON dest.id=sp.location_dest_id
WHERE sp.origin='$ORDER_NAME';
"
