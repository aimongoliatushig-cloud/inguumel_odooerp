# Order flow: hybrid stock policy and cancel (manual test)

## Policy summary

- **Prepaid** (`qpay_paid` / `card_paid` / `wallet_paid`): On confirm → validate outgoing picking (DONE) → On Hand decreases immediately.
- **COD/cash**: On confirm → only reserve (action_assign); On "delivered" status → validate picking (On Hand decreases).
- **Cancel**: If picking not done → unreserve and cancel order. If picking done → create return picking, validate return, then cancel order. Idempotent: no duplicate returns.

## Prerequisites

- Base URL: `https://your-odoo/api/v1` (or `http://localhost:8069/api/v1`)
- Logged-in session cookie or token for auth (replace `YOUR_SESSION_COOKIE` below).
- Create a draft order (e.g. via cart checkout or POST order create) and note `order_id`.

## 1) Prepaid order: confirm → On Hand decreases; cancel → On Hand restored

```bash
# 1a) Confirm with prepaid (e.g. qpay_paid) – picking is validated immediately
curl -s -X POST "https://your-odoo/api/v1/orders/ORDER_ID/confirm" \
  -H "Content-Type: application/json" \
  -H "Cookie: session_id=YOUR_SESSION_COOKIE" \
  -d '{"payment_method": "qpay_paid"}' | jq .

# Expect: 200, success, state "sale", delivery_status_code "received".
# In Inventory: On Hand for the products should have decreased.

# 1b) Cancel the prepaid order – return picking created and validated, then order cancelled
curl -s -X POST "https://your-odoo/api/v1/orders/ORDER_ID/cancel" \
  -H "Content-Type: application/json" \
  -H "Cookie: session_id=YOUR_SESSION_COOKIE" \
  -d '{"reason": "Customer requested"}' | jq .

# Expect: 200, cancelled: true, state "cancel".
# In Inventory: On Hand should be restored (return picking done).

# 1c) Idempotency: call cancel again – no second return, same success
curl -s -X POST "https://your-odoo/api/v1/orders/ORDER_ID/cancel" \
  -H "Content-Type: application/json" \
  -H "Cookie: session_id=YOUR_SESSION_COOKIE" \
  -d '{}' | jq .

# Expect: 200, "Order already cancelled" or same cancelled payload.
```

## 2) COD order: confirm → reserved only; delivered → On Hand decreases; cancel before delivered → unreserve

```bash
# 2a) Confirm with COD – picking only reserved (not validated)
curl -s -X POST "https://your-odoo/api/v1/orders/ORDER_ID/confirm" \
  -H "Content-Type: application/json" \
  -H "Cookie: session_id=YOUR_SESSION_COOKIE" \
  -d '{"payment_method": "cod"}' | jq .

# Expect: 200, state "sale". In Inventory: stock is reserved, On Hand not yet decreased.

# 2b) Cancel before delivered – reservation released, order cancelled (no return)
curl -s -X POST "https://your-odoo/api/v1/orders/ORDER_ID/cancel" \
  -H "Content-Type: application/json" \
  -H "Cookie: session_id=YOUR_SESSION_COOKIE" \
  -d '{"reason": "Cancel before delivery"}' | jq .

# Expect: 200, cancelled: true. Reserved qty should be back to available.
```

## 3) COD order: set status to delivered → On Hand decreases

```bash
# 3a) Confirm COD order (as above).
# 3b) Set delivery status to delivered (staff/warehouse owner; this validates picking)
curl -s -X POST "https://your-odoo/api/v1/orders/ORDER_ID/delivery/status" \
  -H "Content-Type: application/json" \
  -H "Cookie: session_id=YOUR_SESSION_COOKIE" \
  -d '{"status": "delivered"}' | jq .

# Expect: 200. On Hand should decrease at this step.
```

## 4) Error cases (400 VALIDATION_ERROR)

```bash
# 4a) Confirm with insufficient stock (e.g. product qty > available) – prepaid or COD
curl -s -X POST "https://your-odoo/api/v1/orders/ORDER_ID/confirm" \
  -H "Content-Type: application/json" \
  -H "Cookie: session_id=YOUR_SESSION_COOKIE" \
  -d '{"payment_method": "cod"}' | jq .

# Expect: 400, code "VALIDATION_ERROR", message about insufficient stock to reserve.

# 4b) Set delivered when picking cannot be validated (e.g. no picking / wrong state)
# Use an order that has no valid delivery picking or insufficient stock when trying to validate.
curl -s -X POST "https://your-odoo/api/v1/orders/ORDER_ID/delivery/status" \
  -H "Content-Type: application/json" \
  -H "Cookie: session_id=YOUR_SESSION_COOKIE" \
  -d '{"status": "delivered"}' | jq .

# Expect: 400, code "VALIDATION_ERROR", message about delivery picking / validation.
```

## 5) Restart / upgrade

```bash
# Restart Odoo (adjust for your setup)
sudo systemctl restart odoo

# Or upgrade module only
./odoo-bin -c odoo.conf -u inguumel_order_mxm --stop-after-init
```

## Endpoints

| Method | Path | Purpose |
|--------|------|--------|
| POST | `/api/v1/orders/<id>/confirm` | Set payment_method, confirm; prepaid → validate picking, COD → assign only |
| POST | `/api/v1/orders/<id>/cancel` | Cancel order; unreserve or create/validate return then cancel |
| POST | `/api/v1/orders/<id>/delivery/status` | Set delivery status (e.g. delivered); validates picking when setting delivered |
