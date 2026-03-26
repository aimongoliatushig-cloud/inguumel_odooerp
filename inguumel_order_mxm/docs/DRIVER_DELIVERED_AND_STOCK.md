# Driver “Delivered” – Single Source of Truth (On Hand Decrease)

## Summary

- **POST /api/v1/driver/orders/<order_id>/delivery/status** uses the same business logic as **POST /api/v1/orders/<order_id>/delivery/status**.
- Both call `order.sudo()._mxm_set_status("delivered", ...)`, which runs `_mxm_validate_delivery_pickings()`: sets `qty_done` on moves and calls `button_validate()` on **outgoing** pickings only.
- Response shape matches **GET /api/v1/orders/<id>/delivery**: `data` contains `current_status`, `timeline`, `last_update_at`, `version` (no stub placeholders).
- Driver endpoint accepts body **`status`** or **`code`** (e.g. `{"code": "delivered"}`).
- Source for driver is **`drive_app`** (logs and status log source).

## How to test (curl)

### Prerequisites

- Driver user (res.users with `x_warehouse_ids` set).
- COD order in that warehouse, confirmed (so it has an outgoing picking).

### Case 1: Driver marks delivered → picking done, On Hand decreases

```bash
BASE="http://localhost:8069"
TOKEN="<driver_bearer_token>"
ORDER_ID="<sale_order_id>"

# Set delivered (same response shape as GET .../delivery)
curl -s -X POST "$BASE/api/v1/driver/orders/$ORDER_ID/delivery/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"delivered","note":"Driver delivered"}' | jq .

# Or with "code" alias
curl -s -X POST "$BASE/api/v1/driver/orders/$ORDER_ID/delivery/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"code":"delivered"}' | jq .
```

Then:

- **GET delivery** (same payload shape as POST response):

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/v1/orders/$ORDER_ID/delivery" | jq .
# or
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/v1/driver/orders/$ORDER_ID/delivery" | jq .
```

- In Odoo: **Inventory → Transfers**: find the transfer for that order; **state** should be **Done**.
- **On Hand** for the delivered product(s) should be decreased.

### Case 2: Delivered called twice (idempotency)

Call POST with `status: delivered` again for the same order. Expect **200**, same success payload (no duplicate log, no double validation). Second call is a no-op.

### Case 3: Insufficient stock → VALIDATION_ERROR

- Use an order whose products have **no** available quantity in the warehouse (or set On Hand to 0).
- POST `{"status":"delivered"}`. Expect **400** with `code: "VALIDATION_ERROR"` and message like:  
  `Insufficient stock: <Product Name> (required <qty>); ... Check On Hand in warehouse or adjust quantities.`
- Order must **not** be marked delivered; picking must **not** be validated.

### Case 4: Wrong warehouse driver → FORBIDDEN

- Use a driver user whose `x_warehouse_ids` does **not** include the order’s warehouse.
- POST `{"status":"delivered"}`. Expect **403** `FORBIDDEN` (no sudo bypass on permission check).

## Response shape (success)

```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "request_id": "<uuid>",
  "data": {
    "order_id": 123,
    "current_status": { "code": "delivered", "label": "Хүргэгдсэн", "at": "..." },
    "timeline": [ ... ],
    "last_update_at": "...",
    "version": 456
  },
  "meta": null
}
```

## Logging

- On **delivered** success: one structured line with `endpoint=driver`, `order_id`, `user_id`, `warehouse_scope`, `request_id`, `before_status`, `after_status`, `picking_ids`, `picking_states`.
- On validation failure: warning with `request_id` and message.
- On exception: traceback with `request_id` and `order_id`.
