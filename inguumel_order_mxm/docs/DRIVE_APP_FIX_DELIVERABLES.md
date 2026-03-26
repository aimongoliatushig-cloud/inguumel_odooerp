# Inguumel Drive App – Fix Deliverables

**Goal:** Make "Inguumel Drive" app work reliably for warehouse/delivery staff (warehouse_owner).  
**Base URL (example):** `http://72.62.247.95:8069`

---

## 1) Code changes and modules updated

### A) Delivery status init bug

| Module | File | Change |
|--------|------|--------|
| **inguumel_order_mxm** | `models/sale_order.py` | Added `_mxm_ensure_initial_delivery_status()`: idempotent backfill that creates a single `received` log (source=system) when order has no status logs. Called from `_mxm_set_status()` before validating transition so `None → received` is applied when needed. |
| **inguumel_order_mxm** | `controllers/delivery.py` | In `get_delivery`: call `order.sudo()._mxm_ensure_initial_delivery_status()` before `_delivery_payload()` so GET returns `current_status.code` and `timeline` for old orders. |
| **inguumel_order_mxm** | `controllers/driver.py` | In driver `get_delivery`: call `order._mxm_ensure_initial_delivery_status()` before `_delivery_payload()`. POST path already goes through `_mxm_set_status()` which now ensures initial status. |

- Transitions (unchanged): `None → received`; `received → preparing|cancelled`; `preparing → prepared|cancelled`; `prepared → out_for_delivery|cancelled`; `out_for_delivery → delivered|cancelled`; `delivered`/`cancelled` terminal.
- New orders: still get initial `received` on create/confirm (existing logic in `sale_order.create` and `write(state='sale')`).

### B) Route consistency for Drive (driver auth compatibility)

| Module | File | Change |
|--------|------|--------|
| **inguumel_mobile_api** | `controllers/auth.py` | Added `_auth_login_phone_pin(payload, request_id)` returning `(data_dict, None)` or `(None, response)`. Refactored `POST /api/v1/auth/login` to use it. |
| **inguumel_order_mxm** | `controllers/driver.py` | In `POST /api/v1/driver/auth/login`: if body has `phone` and `pin`, call `_auth_login_phone_pin()` and return same JSON as `/api/v1/auth/login`; if user is not `warehouse_owner`, return 403 FORBIDDEN. Legacy `{ login, password }` flow kept. |

- Drive app can use either:
  - **Preferred:** `POST /api/v1/auth/login` with `{ "phone": "...", "pin": "..." }`
  - **Compatibility:** `POST /api/v1/driver/auth/login` with same body `{ "phone", "pin" }` → identical response (uid, partner_id, access_token, expires_in, role, warehouse_ids).

### C) Observability

| Module | File | Change |
|--------|------|--------|
| **inguumel_mobile_api** | `controllers/health.py` | New: `GET /api/v1/health` returns `{ "success": true, "code": "OK", "request_id": "<uuid>", "data": null, "meta": null }`. |
| **inguumel_mobile_api** | `controllers/__init__.py` | Import `health` controller. |
| **inguumel_mobile_api** | `controllers/auth.py` | Exception logs in login/logout/me include `request_id` in message. |
| **inguumel_order_mxm** | `controllers/orders.py` | Exception log for mxm.orders create includes `request_id`. |

- All API responses already include `request_id`; exception handlers now log `request_id` consistently.

---

## 2) Endpoints affected and example curl

### Health

```bash
curl -s "http://72.62.247.95:8069/api/v1/health" | jq .
# Expect: success: true, code: "OK", request_id: "<uuid>"
```

### Auth (staff / warehouse owner – phone + pin)

```bash
# Preferred
curl -s -X POST "http://72.62.247.95:8069/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"<STAFF_PHONE>","pin":"<PIN>"}' | jq .

# Compatibility (Drive app)
curl -s -X POST "http://72.62.247.95:8069/api/v1/driver/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"<STAFF_PHONE>","pin":"<PIN>"}' | jq .
# Same response: uid, partner_id, access_token, expires_in, role: "warehouse_owner", warehouse_ids
```

### Orders list (warehouse-scoped)

```bash
TOKEN="<access_token from login>"
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://72.62.247.95:8069/api/v1/mxm/orders" | jq .
```

### Delivery read (no more false / empty timeline for old orders)

```bash
ORDER_ID=5
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://72.62.247.95:8069/api/v1/orders/$ORDER_ID/delivery" | jq .
# Expect: data.current_status.code (e.g. "received"), data.timeline (non-empty after init)
```

### Delivery status update

```bash
curl -s -X POST "http://72.62.247.95:8069/api/v1/orders/$ORDER_ID/delivery/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"preparing"}' | jq .
# Expect: success: true, data with current_status and timeline
```

### Driver-scoped delivery (same contract)

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "http://72.62.247.95:8069/api/v1/driver/orders/$ORDER_ID/delivery" | jq .

curl -s -X POST "http://72.62.247.95:8069/api/v1/driver/orders/$ORDER_ID/delivery/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"prepared","note":"Ready"}' | jq .
```

---

## 3) Odoo upgrade steps

1. **Restart Odoo** (to load new Python code):
   ```bash
   sudo systemctl restart odoo
   # or however your instance is run
   ```

2. **Upgrade modules** (Apps → find and upgrade):
   - **inguumel_mobile_api** (health route + auth refactor)
   - **inguumel_order_mxm** (delivery init + driver auth compatibility)

   Or via CLI:
   ```bash
   ./odoo-bin -c odoo.conf -u inguumel_mobile_api,inguumel_order_mxm --stop-after-init
   ```
   Then restart the service.

---

## 4) Migration / backfill for old orders with None status

- **No separate migration script is required.** Backfill is **on-demand and idempotent**:
  - **GET** `/api/v1/orders/<id>/delivery` or **GET** `/api/v1/driver/orders/<id>/delivery`: before building the response, the backend calls `_mxm_ensure_initial_delivery_status()`. If the order has no status logs, it creates one `received` log and sets `mxm_delivery_status = 'received'`.
  - **POST** `/api/v1/orders/<id>/delivery/status` or **POST** `/api/v1/driver/orders/<id>/delivery/status`: `_mxm_set_status()` calls `_mxm_ensure_initial_delivery_status()` before validating the transition, so the first status update on an old order also creates the initial `received` log if missing.

- **Optional bulk backfill** (e.g. for reporting or to avoid lazy init on first access): run in Odoo shell:
  ```python
  SaleOrder = env['sale.order'].sudo()
  orders = SaleOrder.search([('mxm_delivery_status', '=', False)])
  for order in orders:
      order._mxm_ensure_initial_delivery_status()
  env.cr.commit()
  ```
  Or limit to confirmed sales: add `('state', '=', 'sale')` to the domain.

---

## 5) Contract unchanged (DO NOT change)

- Response field names for:
  - `POST /api/v1/auth/login`
  - `GET /api/v1/mxm/orders`
  - `GET /api/v1/orders/<id>/delivery`
  - `POST /api/v1/orders/<id>/delivery/status`
- Mobile customer app behavior and endpoints are unchanged.

---

## 6) Summary

| Item | Status |
|------|--------|
| Every order gets initial delivery status `received` when first read or first status update (idempotent) | Done |
| Transition None → received allowed; then received → preparing → … enforced | Already in model; ensured by init |
| GET/POST delivery (and driver variants) use initializer | Done |
| POST /api/v1/driver/auth/login accepts { phone, pin } and returns same JSON as /api/v1/auth/login | Done |
| GET /api/v1/health | Done |
| request_id in responses and exception logs | Done |
