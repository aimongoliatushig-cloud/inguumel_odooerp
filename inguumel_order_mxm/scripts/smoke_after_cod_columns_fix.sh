#!/usr/bin/env bash
# Smoke test after fixing x_cod_confirmed UndefinedColumn (module upgrade).
# Run from server: ./scripts/smoke_after_cod_columns_fix.sh
set -e
BASE="${BASE:-http://127.0.0.1:8069}"
LOG="${LOG:-/opt/odoo/log/odoo19.log}"

echo "=== 1. Odoo service active ==="
systemctl is-active odoo19 || true

echo ""
echo "=== 2. Recent UndefinedColumn (last 5, should be old timestamps before upgrade) ==="
grep -a "UndefinedColumn" "$LOG" 2>/dev/null | tail -5 || echo "None found"

echo ""
echo "=== 3. DB columns exist on sale_order ==="
sudo -u postgres psql -d InguumelStage -t -c "SELECT column_name FROM information_schema.columns WHERE table_name='sale_order' AND column_name IN ('x_cod_confirmed','x_cod_amount','x_cash_confirmed_at','x_cash_confirmed_by');" 2>/dev/null || echo " (run as user with DB access)"

echo ""
echo "=== 4. API reachability (delivery endpoint without auth => 401) ==="
CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BASE/api/v1/orders/1/delivery" -H "Content-Type: application/json")
echo "GET /api/v1/orders/1/delivery => HTTP $CODE (expected 401)"

echo ""
echo "=== 5. Login (expect 400 without body; or 200 with valid credentials) ==="
curl -s -o /dev/null -w "POST /api/v1/auth/login => HTTP %{http_code}\n" "$BASE/api/v1/auth/login" -H "Content-Type: application/json" -d '{}'

echo ""
echo "Done. If no new UndefinedColumn after restart and columns exist, fix is verified."
