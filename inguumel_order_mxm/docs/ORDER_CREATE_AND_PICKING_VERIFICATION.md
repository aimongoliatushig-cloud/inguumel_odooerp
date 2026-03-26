# Order create + picking verification (POST/GET MXM orders)

## Summary of code changes

### A) POST /api/v1/mxm/orders (`controllers/orders.py`)

- **Warehouse from request**: Accepts `warehouse_id` in JSON body; validates it exists and belongs to user's company. Fallback: user/company warehouse.
- **Order creation**: `partner_id`, `warehouse_id`, `order_line` (product_id, qty, price_unit optional) with bounds (qty ≤ 999, items ≤ 50).
- **Confirm**: Calls `order.action_confirm()` so delivery workflow starts.
- **Picking check**: After confirm, requires at least one **outgoing** picking in `order.picking_ids`. If none, raises `UserError` → transaction rolled back, returns 422 with `NO_PICKING_CREATED` and `message_mn`.
- **Response**: Always JSON. Success: `{ "success": true, "data": { "order_id", "order_number", "picking_id", "state" }, "request_id": "..." }`. Error: `{ "success": false, "code": "...", "message": "...", "request_id": "...", "data": { "message_mn": "..." } }`.

### B) GET /api/v1/mxm/orders list (`controllers/order_list.py`)

- **Delivery status fields** added to each order item:
  - `delivery_status_code`: received | preparing | prepared | out_for_delivery | delivered | cancelled
  - `delivery_status_label_mn`: Mongolian label
  - `is_delivered`, `is_cancelled`: booleans  
  So mobile can filter without N+1.

### C) Delivery/POS visibility

- **"Хүргэлт" (Inguumel → Хүргэлт)**: `sale.order` list with domain `[('state', 'in', ['sale', 'done'])]`. Confirmed orders appear there; `mxm_delivery_status` / `mxm_last_status_label_mn` come from status logs (set on create/confirm by `sale.order` create/write).
- **Inventory → Operations → Transfers**: `stock.picking` list. Outgoing pickings are created by `sale_stock` on `action_confirm()`; `stock.picking` inherits `mxm_sale_order_id` (from `sale_id` / origin), so MXM filters (e.g. "Захиалга авлаа") work.

---

## 1) Create order (expect 200 + order_id + picking_id)

```bash
# Set base URL and a valid Bearer token (from login)
BASE="http://localhost:8069"
TOKEN="your_access_token_here"

# Create order with warehouse_id and items
curl -s -X POST "$BASE/api/v1/mxm/orders" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "warehouse_id": 1,
    "items": [
      { "product_id": 1, "qty": 2 },
      { "product_id": 2, "qty": 1 }
    ]
  }' | jq .
```

**Expected (success):** HTTP 200, body like:

```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "request_id": "<uuid>",
  "data": {
    "order_id": 123,
    "order_number": "S00123",
    "picking_id": 456,
    "state": "sale"
  },
  "meta": null
}
```

---

## 2) List orders (expect delivery_status_code included)

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders?limit=5" | jq '.data[0] | {
  order_id,
  order_number,
  delivery_status_code,
  delivery_status_label_mn,
  is_delivered,
  is_cancelled
}'
```

**Expected:** Each element in `data` has `delivery_status_code`, `delivery_status_label_mn`, `is_delivered`, `is_cancelled`.

---

## 3) Verify picking exists in Odoo (by order_id)

```bash
# After create, use order_id from step 1
ORDER_ID=123
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders/$ORDER_ID" | jq '.data | {
  order_number,
  state,
  delivery_status_code,
  delivery_status_label_mn
}'
```

Then in Odoo UI: **Inventory → Transfers** and filter by origin = order number (e.g. S00123), or open the picking by ID from the create response.

---

## Odoo shell verification

Run in project root (or where `odoo` or `odoo-bin` is):

```bash
# Example: Odoo 19 Community
./odoo-bin shell -c /path/to/odoo.conf -d your_database
```

Then in shell:

```python
# By order ID (from API response)
order_id = 123  # replace with real order_id
order = env['sale.order'].browse(order_id)
print("Order:", order.name, "State:", order.state, "Warehouse:", order.warehouse_id.name)
print("Pickings:", order.picking_ids.ids)
outgoing = order.picking_ids.filtered(lambda p: p.picking_type_id.code == 'outgoing')
print("Outgoing picking(s):", outgoing.mapped('name'))
for p in outgoing:
    print("  ", p.name, "State:", p.state, "Type:", p.picking_type_id.name)
# Delivery status (MXM)
print("mxm_delivery_status:", order.mxm_delivery_status)
print("mxm_last_status_code:", order.mxm_last_status_code)
```

Expected: at least one outgoing picking (WH/OUT/xxxx), `order.state == 'sale'`, `mxm_delivery_status` or `mxm_last_status_code` set (e.g. `received`).

---

## Restart/upgrade

```bash
# Restart Odoo service (adjust service name as needed)
sudo systemctl restart odoo

# Or if upgrading module
./odoo-bin -c odoo.conf -d your_database -u inguumel_order_mxm --stop-after-init
```
