# Order flow & POS – test checklist and curl commands

## Summary of changes

### 1. Confirm flow (checkout → address → confirm)
- **POST /api/v1/mxm/cart/checkout**: Creates **draft** sale.order only (no `action_confirm`). Uses `sudo()` for create so portal users do not hit ACL/sequence errors. Returns `order_id`, `order_number`, `state` (draft). Clears cart.
- **PUT/POST /api/v1/orders/<order_id>/address**: Sets `x_delivery_address`, `x_phone_primary`, `x_phone_secondary`. Ownership validated (order.partner_id == current user's partner).
- **POST /api/v1/orders/<order_id>/confirm**: Validates (draft, warehouse, lines, address, amount_total > 0, payment_method). Sets `x_payment_method`, calls `action_confirm()`, ensures "Захиалга авлаа" (received). Returns 200 with `state`, `next_step`, `delivery_status_code`. Validation failures → 400 `VALIDATION_ERROR` with `errors` dict.

### 2. POS online orders
- **GET /api/v1/pos/online-orders**: Query params: `config_id` (pos.config id, resolves warehouse from `pos.config.warehouse_id`) or `warehouse_id`, `state=pending|delivered|cancelled`, `limit`, `offset`. Returns sale orders (mobile) for that warehouse. Auth: Bearer (user must have warehouse scope). `state=pending` => not delivered/cancelled (received, preparing, prepared, out_for_delivery). POS can set delivery status via existing **POST /api/v1/orders/<order_id>/delivery/status** (staff/warehouse owner).

### 3. Error handling
- **order_create** (`/api/v1/mxm/order/create`): `UserError`/`ValidationError` → 400 `VALIDATION_ERROR`. Unexpected → 500 `SERVER_ERROR` with `request_id`.
- **order_flow** (address, confirm): Validation → 400 with `errors`. `AccessError` → 403. Unexpected → 500 `SERVER_ERROR` with `request_id`.
- **cart checkout**: Exception → 500 `SERVER_ERROR` with `request_id`.

### 4. Fields on sale.order (existing)
- `x_payment_method`: cod | qpay_pending (API accepts "cash" → cod).
- `mxm_delivery_status`: received | preparing | prepared | out_for_delivery | delivered | cancelled (canonical; no `x_delivery_status` added).
- `warehouse_id`: already on order.

---

## Test checklist (curl)

Set:
```bash
BASE="http://localhost:8069"
# Get token from login (see step 0)
TOKEN="<access_token>"
```

### 0. Login (get Bearer token)
```bash
curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"<customer_phone>","pin":"<pin>"}' | jq .
# Use .data.access_token as TOKEN
```

### 1. Cart checkout (draft order)
```bash
# Ensure cart has lines (POST /api/v1/mxm/cart/lines if needed), then:
curl -s -X POST "$BASE/api/v1/mxm/cart/checkout?warehouse_id=1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" | jq .
# Expect: 200, data.order_id, data.order_number, data.state = "draft"
```

### 2. Attach address
```bash
ORDER_ID=<from step 1>
curl -s -X POST "$BASE/api/v1/orders/$ORDER_ID/address" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"delivery_address":"Улаанбаатар, 1-р хороо","phone_primary":"99112233"}' | jq .
# Expect: 200, data.order_id, data.order_number
```

### 3. Confirm order (cash)
```bash
curl -s -X POST "$BASE/api/v1/orders/$ORDER_ID/confirm" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"payment_method":"cash"}' | jq .
# Expect: 200, data.state = "sale", data.next_step = "received", data.delivery_status_code = "received"
# If 400: check .errors for delivery_address, payment_method, etc.
```

### 4. Verify in delivery list (Odoo UI)
- Inguumel → Хүргэлт: order should appear with status "Захиалга авлаа".
- Inventory → Operations → Transfers: WH/OUT for that order should exist.

### 5. POS online orders (use warehouse owner or staff token)
```bash
# With token that has warehouse scope (e.g. driver/warehouse user):
curl -s "$BASE/api/v1/pos/online-orders?warehouse_id=1&state=pending&limit=10" \
  -H "Authorization: Bearer $TOKEN" | jq .
# Expect: 200, data = array of orders with order_number, phone, delivery_address, amount_total, delivery_status_code, lines
```

### 6. Status transitions (POS / staff)
```bash
# Set status to preparing (requires staff or warehouse owner token):
curl -s -X POST "$BASE/api/v1/orders/$ORDER_ID/delivery/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"preparing"}' | jq .
```

### 7. Reproduce confirm error (validation)
```bash
# Confirm without address (if order has no x_delivery_address and partner has no street):
curl -s -X POST "$BASE/api/v1/orders/$ORDER_ID/confirm" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"payment_method":"cod"}' | jq .
# Expect: 400, code = VALIDATION_ERROR, errors.delivery_address = "required"
```

---

## Root cause of "Алдаа гарлаа. Дахин оролдоно уу."

1. **Portal user creating order**: Cart checkout previously used `SaleOrder.with_user(user).create()`; portal users can hit **AccessError** on `ir.sequence` or create rights → 500 "Internal error" → app shows generic message. **Fix**: Use `env["sale.order"].sudo().create()` in checkout and set `company_id`/`warehouse_id` so record rules still apply.
2. **Missing address on confirm**: If the app called a non-existent "confirm" endpoint or a flow that skipped address, backend could return 404/500. **Fix**: New **POST /api/v1/orders/<id>/confirm** with explicit validation and 400 + `errors` for missing address/payment_method.
3. **ValidationError in action_confirm**: e.g. product not sellable, stock rule. **Fix**: order_create and order_flow catch `UserError`/`ValidationError` and return 400 with message instead of 500.

Use **request_id** in logs and in every JSON response to correlate failures in Odoo logs.
