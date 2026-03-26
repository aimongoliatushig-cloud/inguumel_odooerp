# Payment Flow Refactor, Logging & Response Shape

## A) Structured debug logs – GET /api/v1/mxm/orders

**Added:** One structured log line per request with:

- `request_id`
- `uid` (logged-in user id)
- `partner_id` (user's partner)
- `warehouse_id_query` (raw query param)
- `domain` (computed search domain)
- `result_count` (len(items))
- `total` (total matching orders)

**Example log:**

```
order.list request_id=abc-123 uid=6 partner_id=11 warehouse_id_query=1 domain=[('partner_id', '=', 11), ('warehouse_id', '=', 1)] result_count=2 total=2
```

**File:** `inguumel_order_mxm/controllers/order_list.py` (around the search and return).

---

## B) Response shape – backward compatible

**Current (unchanged when no param):**

```json
{ "success": true, "data": [...], "meta": { "count": 2, "total": 2, "limit": 20, "offset": 0 } }
```

**New shape (opt-in via query param):**

Add `?wrap=1` (or `wrap=true` or `wrap=items`) to GET `/api/v1/mxm/orders`:

```json
{ "success": true, "data": { "items": [...], "meta": { "count": 2, "total": 2, "limit": 20, "offset": 0 } } }
```

**Backward compatibility:** Existing clients that omit `wrap` keep the current shape. New clients use `?wrap=1` for the nested `data.items` + `data.meta` shape.

**Example:**

```bash
curl -s -b /tmp/mxm_cookies.txt "$BASE/api/v1/mxm/orders?wrap=1" | jq .
```

---

## C) Payment flow refactor

### Design

| Payment method   | Order state after create | When confirmed |
|------------------|---------------------------|-----------------|
| **COD**          | Confirmed immediately (or draft if config says so) | On create (or never until manual confirm) |
| **QPay**         | **Draft**                 | **Only after QPay callback with status=success** |

### Code changes

1. **Order service** (`inguumel_order_mxm/services/order_service.py`)
   - If `payment_method == "qpay_pending"`: do **not** call `action_confirm()`; leave order in draft.
   - If `payment_method == "cod"`: keep existing behaviour (confirm when `auto_confirm` is True).

2. **QPay callback** (`inguumel_order_mxm/controllers/payment.py`)
   - **Route:** `POST /api/v1/mxm/payment/qpay/callback`
   - **Body (JSON):** `order_id` or `order_number`, `status` (`"success"` | `"failed"`), optional `transaction_id`.
   - **Behaviour:**  
     - On `status == "success"`: find order by `order_id` or `order_number`; if `state == "draft"` and `x_payment_method == "qpay_pending"`, call `order.action_confirm()`.  
     - On `status == "failed"`: only log; order stays draft.
   - **Kill-switch:** `ir.config_parameter` key `api_disabled:/api/v1/mxm/payment/qpay/callback` = `"1"`/`"true"` → 503.

### Security note (production)

- Callback is `auth="public"`. In production you should:
  - Verify QPay signature/token if they provide one (e.g. header or body field).
  - Optionally restrict by IP or use a shared secret in `ir.config_parameter` and validate a token in the request.

### COD behaviour

- COD still uses existing `auto_confirm` logic: confirm immediately when `mxm_order.auto_confirm` is enabled.
- To keep COD orders in draft until manual confirm, set `mxm_order.auto_confirm` = `"0"` (and handle confirm in UI/workflow).

### Example: create QPay order then callback

```bash
# 1) Create order (stays draft)
curl -s -b /tmp/mxm_cookies.txt -X POST "$BASE/api/v1/mxm/order/create?warehouse_id=1" \
  -H "Content-Type: application/json" \
  -d '{"phone_primary":"99112233","delivery_address":"Test","payment_method":"qpay_pending"}' | jq .
# data.status should be "draft" (or order state draft)

# 2) Simulate QPay callback (after payment success)
curl -s -X POST "$BASE/api/v1/mxm/payment/qpay/callback" \
  -H "Content-Type: application/json" \
  -d '{"order_id": 7, "status": "success", "transaction_id": "qpay-123"}' | jq .
# Order 7 is confirmed; response includes payment_status / status.
```

---

## Summary

| Item              | Change |
|-------------------|--------|
| **Logging**       | GET `/api/v1/mxm/orders` logs request_id, uid, partner_id, warehouse_id query, domain, result_count, total. |
| **Response shape**| Optional `?wrap=1`: `data` becomes `{ "items": [...], "meta": {...} }`; default unchanged. |
| **QPay**          | Order created in draft; confirmed only when callback `status=success`. |
| **QPay callback** | `POST /api/v1/mxm/payment/qpay/callback` with order_id/order_number + status. |
| **COD**           | Unchanged: confirm on create when auto_confirm is True. |
