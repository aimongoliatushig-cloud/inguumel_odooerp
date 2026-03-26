# COD Auto-Paid Verification

## Config Parameters

| Key | Default | Description |
|-----|---------|-------------|
| `inguumel.cod_auto_paid_enabled` | `false` | Kill switch. Set to `true` or `1` to enable. |
| `inguumel.cod_auto_paid_delay_minutes` | `10` | Safety delay: only auto-paid if delivered_at is older than N minutes. |

## SQL: List delivered + COD + not paid orders

```sql
SELECT so.id, so.name, so.partner_id, so.warehouse_id, so.amount_total,
       so.x_payment_method, so.x_paid, so.mxm_delivery_status, so.state
FROM sale_order so
WHERE so.x_payment_method = 'cod'
  AND so.state IN ('sale', 'done')
  AND so.amount_total > 0
  AND (so.x_paid IS NULL OR so.x_paid = false)
  AND so.mxm_delivery_status = 'delivered'
  AND EXISTS (
    SELECT 1 FROM stock_picking sp
    JOIN stock_picking_type spt ON sp.picking_type_id = spt.id
    WHERE sp.origin = so.name
      AND spt.code = 'outgoing'
      AND sp.state = 'done'
  )
ORDER BY so.id
LIMIT 200;
```

## Test Steps

### 1. Enable COD auto-paid

```sql
UPDATE ir_config_parameter
SET value = 'true'
WHERE key = 'inguumel.cod_auto_paid_enabled';
```

Or via Odoo: Settings → Technical → Parameters → System Parameters.

### 2. Simulate: create COD order, deliver, wait, run cron

- Create COD order from mobile app.
- Deliver: set `mxm_delivery_status = 'delivered'` (Delivery Workbench or driver API).
- Ensure outgoing picking is `state = 'done'`.
- Wait 10+ minutes (or set `inguumel.cod_auto_paid_delay_minutes` to 0 for testing).
- Trigger cron manually or wait 5 minutes:

```bash
# Via Odoo shell
odoo shell -c /path/to/odoo.conf -d your_db
>>> env['sale.order']._cron_cod_auto_paid()
>>> env.cr.commit()
```

### 3. Verify Lucky Wheel eligibility

```bash
BASE="http://localhost:8069"
TOKEN=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"95909912","pin":"050206"}' | jq -r '.data.access_token // empty')
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/v1/lucky-wheel/eligibility?warehouse_id=1" | jq .
```

Expected: `accumulated_paid_amount` and `spin_credits` increase after COD order is auto-paid.

### 4. Idempotency

Run cron again. Already-paid orders must not be re-marked. Check:

```sql
SELECT id, name, x_paid, x_cod_auto_paid, x_paid_at
FROM sale_order
WHERE x_payment_method = 'cod' AND x_paid = true;
```

## Upgrade Commands

```bash
# Upgrade only affected modules
odoo -c /path/to/odoo.conf -d your_db -u inguumel_order_mxm --stop-after-init

# Restart Odoo
sudo systemctl restart odoo
```
