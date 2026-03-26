#!/usr/bin/env bash
# Upgrade inguumel_order_mxm and smoke-test MXM rule (no Transit/MTO).
# Usage: run as root or with sudo for systemctl; DB name InguumelStage by default.

set -e
DB="${1:-InguumelStage}"

echo "=== Stopping Odoo 19 ==="
sudo systemctl stop odoo19 || true

echo "=== Upgrading inguumel_order_mxm ==="
sudo -u odoo /opt/odoo/venv/bin/python /opt/odoo/odoo19/odoo-bin -c /etc/odoo19.conf -d "$DB" -u inguumel_order_mxm --stop-after-init

echo "=== Starting Odoo 19 ==="
sudo systemctl start odoo19

echo "=== Smoke: create MXM order (product 3714, qty 1) ==="
echo "Run from a host that can reach the API (replace URL and auth):"
echo '  curl -s -X POST "http://localhost:8069/api/v1/mxm/orders" \'
echo '    -H "Content-Type: application/json" \'
echo '    -d "{\"items\":[{\"product_id\":3714,\"qty\":1}]}"'
echo ""
echo "Check logs for:"
echo "  - [MXM_ORDER_DIAG] route_id=3 and line route_ids=[3]"
echo "  - [MXM_LAUNCH_STOCK_RULE] (for consu lines)"
echo "  - [MXM_RULE] Replacing... or Filtered... (if core had chosen Transit/MTO)"
echo "  API success=true and picking_id present."
echo ""
echo "SQL verify (run in psql or Odoo shell):"
echo "  SELECT so.name, sp.id, pt.code, dest.complete_name"
echo "  FROM sale_order so"
echo "  JOIN stock_picking sp ON sp.origin=so.name"
echo "  JOIN stock_picking_type pt ON pt.id=sp.picking_type_id"
echo "  JOIN stock_location dest ON dest.id=sp.location_dest_id"
echo "  WHERE so.origin='MXM API'"
echo "  ORDER BY so.id DESC LIMIT 5;"
echo "  --> Expect pt.code='outgoing' and dest.usage='customer', not transit."
