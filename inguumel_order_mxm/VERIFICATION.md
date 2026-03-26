# Order Creation Fix Verification

## Root Causes Identified and Fixed

### 1. ✅ FIXED: `x_phone_2` column missing
- **Issue**: `column res_partner.x_phone_2 does not exist`
- **Root cause**: Field defined in code but module not upgraded
- **Fix**: Upgraded `inguumel_mobile_api` module
- **Verification**: `SELECT column_name FROM information_schema.columns WHERE table_name='res_partner' AND column_name='x_phone_2';` returns row

### 2. ✅ FIXED: `product_uom` vs `product_uom_id` 
- **Issue**: `Invalid field 'product_uom'` on sale.order.line
- **Root cause**: Wrong field name in order line creation
- **Fix**: Changed `product_uom` to `product_uom_id` in `order_service.py` line 120
- **File**: `/opt/odoo/custom_addons/inguumel_order_mxm/services/order_service.py`

### 3. ✅ ALREADY FIXED: ir.sequence AccessError
- **Issue**: Portal users cannot read ir.sequence during order creation
- **Root cause**: Order creation without sudo()
- **Fix**: Already implemented - `SaleOrder.sudo().create()` at line 145
- **File**: `/opt/odoo/custom_addons/inguumel_order_mxm/services/order_service.py`

## Changes Made

### File: `inguumel_order_mxm/services/order_service.py`
- **Line 120**: `"product_uom_id": line.product_id.uom_id.id` (was `product_uom`)
- **Line 145**: `SaleOrder = env["sale.order"].sudo()` (already correct)
- **Line 132**: Added `"company_id": company_id` to preserve record rules

### Database Schema
```sql
-- Verified columns exist:
res_partner.x_phone_2          ✓
sale_order.x_delivery_address  ✓
sale_order.x_phone_primary     ✓
sale_order.x_phone_secondary   ✓
sale_order.x_payment_method    ✓
```

## Test Script Created

**Location**: `/opt/odoo/custom_addons/inguumel_order_mxm/scripts/test_order_create.sh`

**Usage**:
```bash
# 1. Login first (get cookies)
curl -c /tmp/mxm_cookies.txt -H "Content-Type: application/json" \
  -d '{"phone":"+97699112233","pin":"YOUR_PIN"}' \
  http://127.0.0.1:8069/api/v1/auth/login

# 2. Run test
PRODUCT_ID=7 WAREHOUSE_ID=1 bash /opt/odoo/custom_addons/inguumel_order_mxm/scripts/test_order_create.sh
```

## Verification Commands

### 1. Check Odoo is running
```bash
sudo systemctl status odoo19
```

### 2. Check no errors in logs
```bash
sudo journalctl -u odoo19 --since "5 minutes ago" | grep -E "(ERROR|CRITICAL)"
```

### 3. Test auth endpoint
```bash
curl -s -c /tmp/mxm_cookies.txt -H "Content-Type: application/json" \
  -d '{"phone":"+97699112233","pin":"YOUR_PIN"}' \
  http://127.0.0.1:8069/api/v1/auth/login | jq .
```

### 4. Test auth/me (should not error on x_phone_2)
```bash
curl -s -b /tmp/mxm_cookies.txt http://127.0.0.1:8069/api/v1/auth/me | jq .
```

### 5. Test order creation
```bash
# Add to cart
curl -s -b /tmp/mxm_cookies.txt -X POST http://127.0.0.1:8069/api/v1/mxm/cart/lines \
  -H "Content-Type: application/json" \
  -d '{"product_id":7,"qty":1,"warehouse_id":1}' | jq .

# Create order
curl -s -b /tmp/mxm_cookies.txt -X POST http://127.0.0.1:8069/api/v1/mxm/order/create \
  -H "Content-Type: application/json" \
  -d '{"phone_primary":"99112233","delivery_address":"Test"}' | jq .
```

## Expected Results

All endpoints should return:
- HTTP 200 (or 400 for validation errors with proper error codes)
- JSON with `{"success": true, ...}` or `{"success": false, "code": "...", ...}`
- No `x_phone_2 does not exist` errors
- No `product_uom` errors  
- No `ir.sequence` AccessError

## Rollback Plan (if needed)

```bash
# Stop Odoo
sudo systemctl stop odoo19

# Restore from backup (if you have one)
# sudo -u postgres pg_restore ...

# Or downgrade module
sudo -u odoo /opt/odoo/venv/bin/python /opt/odoo/odoo19/odoo-bin \
  -c /etc/odoo19.conf -d InguumelStage \
  -u inguumel_mobile_api,inguumel_order_mxm --stop-after-init

# Start Odoo
sudo systemctl start odoo19
```
