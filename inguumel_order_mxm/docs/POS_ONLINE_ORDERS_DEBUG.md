# POS Online Orders – endpoint, filters, permissions

## Purpose
**Delivery POS** (“Хүргэлтийн POS”) and **Inguumel Delivery Workbench** must show the same online (mobile) orders: `sale.order` records with `state in ['sale','done']`, scoped by warehouse. No duplication: one source of truth (sale.order), one canonical API for POS list.

## Canonical endpoint
**GET /api/v1/pos/online-orders**

| Param        | Required | Description |
|-------------|----------|-------------|
| `warehouse_id` | Yes*   | Warehouse ID (branch). *Or use `config_id` to resolve from pos.config.warehouse_id. |
| `config_id` | No       | POS config ID; if set, warehouse is taken from pos.config.warehouse_id (inguumel_credit_pos). |
| `state`     | No       | `pending` (default), `delivered`, or `cancelled`. |
| `limit`     | No       | Max 50, default 20. |
| `offset`    | No       | Pagination. |

**Auth:** Bearer token (logged-in user).  
**Response:** `{ success, code, message, request_id, data: [ {...} ], meta: { count, total, limit, offset } }`.

### Data shape (each item)
| Field | Description |
|-------|-------------|
| order_id | sale.order id |
| order_number | e.g. S00042 |
| warehouse_id | Warehouse (branch) id |
| customer_name | Partner name (same as partner_name) |
| phone_primary | Order or partner phone |
| phone_secondary | Optional |
| delivery_address | x_delivery_address |
| total_amount | amount_total (number) |
| state | sale / done |
| mxm_delivery_status | received, preparing, prepared, out_for_delivery, delivered, cancelled |
| delivery_status_code | Same as mxm_delivery_status |
| delivery_status_label_mn | Mongolian label |
| last_change | mxm_last_status_at or write_date (YYYY-MM-DD HH:MM:SS) |
| lines | [{ product_id, product_name, qty, price_unit }] |

## Filters (aligned with Delivery Workbench)
- **Base:** `warehouse_id = <requested>`, `state in ['sale','done']` (confirmed orders only; no draft).
- **state=pending:** Orders not yet delivered/cancelled:  
  `mxm_delivery_status in (False, 'received', 'preparing', 'prepared', 'out_for_delivery')`.  
  `False` includes newly confirmed orders where status is not yet set (same visibility as Workbench).
- **state=delivered:** `mxm_delivery_status = 'delivered'`.
- **state=cancelled:** `mxm_delivery_status = 'cancelled'`.

## Permissions
- **Warehouse owner (x_warehouse_ids):** Can load online orders only for warehouses in `x_warehouse_ids`. Requested `warehouse_id` must be in that set.
- **Stock user (no x_warehouse_ids):** Can load online orders for any warehouse of the **same company** (so Delivery POS at a branch works for stock users assigned to that company).
- **Others:** 403 FORBIDDEN.

## Who should call this
- **Delivery POS** (React Native or Odoo POS UI) must call **GET /api/v1/pos/online-orders?warehouse_id=&lt;id&gt;&state=pending** with the staff Bearer token. Use the warehouse for the current branch (e.g. from POS config or staff context).
- **Delivery Workbench** uses Odoo UI (sale.order list with domain `[('state','in',['sale','done'])]`); no need to call this API for the workbench. Consistency is ensured by same model and same logical filters (confirmed + pending = not delivered/cancelled).

## Curl proof (production checklist)
```bash
BASE="http://<host>:8069"
# Use a POS/delivery staff token (warehouse owner or stock user for that company)
POS_TOKEN="<bearer_token>"

# Same orders as Delivery Workbench for warehouse 1, pending
curl -s "$BASE/api/v1/pos/online-orders?warehouse_id=1&state=pending" \
  -H "Authorization: Bearer $POS_TOKEN" | jq .

# Expect: 200, success true, data = array of sale orders with order_number, customer_name, phone_primary, delivery_address, total_amount, mxm_delivery_status, last_change, lines.
# If 403: user has no warehouse scope and is not stock user, or warehouse not in company.
# If 400: missing warehouse_id (or invalid config_id).
```

### Quick manual test (expect 200, array length)
```bash
# Replace BASE and TOKEN; warehouse_id=1 must exist and user must have scope.
curl -s -w "\nHTTP_CODE:%{http_code}" "$BASE/api/v1/pos/online-orders?warehouse_id=1&state=pending" \
  -H "Authorization: Bearer $TOKEN" -o /tmp/pos_orders.json
HTTP_CODE=$(tail -n1 /tmp/pos_orders.json)
BODY=$(head -n -1 /tmp/pos_orders.json)
echo "HTTP: $HTTP_CODE"
echo "$BODY" | jq '{ success, code, length: (.data | length), total: .meta.total }'
# Expect: HTTP: 200, success true, length = number of pending orders, total same.
```

## If Delivery POS list is empty
1. **Endpoint:** Confirm the app calls **GET /api/v1/pos/online-orders** (not an old or different URL).
2. **Warehouse:** Pass the correct `warehouse_id` for the branch. If using `config_id`, set **pos.config.warehouse_id** for that config; else the API falls back to first warehouse in scope/company.
3. **Auth:** Use a Bearer token for a user who is either (a) warehouse owner with that warehouse in `x_warehouse_ids`, or (b) stock user in the same company as the warehouse.
4. **Filter:** Use `state=pending` to see non-delivered orders; backend now includes `mxm_delivery_status = False` so newly confirmed orders appear.
5. **Odoo:** In Settings / Users, ensure the POS/delivery user has either “Warehouse user” (stock) and access to the right company, or “Warehouse” assignments (x_warehouse_ids) for the branch.

**Domain that controls visibility:** `warehouse_id = <requested>`, `state in ['sale','done']`, and for pending: `mxm_delivery_status` False or in (received, preparing, prepared, out_for_delivery). See **DELIVERY_POS_VISIBILITY_AND_STOCK_POLICY.md** for root cause and fixes.
