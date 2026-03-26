# Step 3: Delivery Status → Picking-Based Stock Reality

## Summary

Delivery app status updates are now **strictly tied to warehouse movements**. Timeline cannot diverge from stock reality.

## 1) Source of Truth

For each `sale.order`:

- **Source of truth**: Outgoing pickings (`stock.picking` with `picking_type_id.code == 'outgoing'`)
- Link: `picking.sale_id` / `picking.origin` contains order reference
- Helper: `order._mxm_get_outgoing_pickings()` → pickings sorted by `create_date`

**If no outgoing picking exists** when driver/staff updates status (except initial `None → received`):

- Return **400** with `code="NO_DELIVERY_PICKING"`
- Message: `"No delivery picking found. Confirm the order to create one."`
- Timeline is **not** updated

## 2) Status → Picking Mapping

| Status            | Stock Effect | Picking Action              | Notes                                           |
|-------------------|--------------|-----------------------------|-------------------------------------------------|
| received          | none         | —                           | Timeline only; initial can be set without picking |
| preparing         | none         | —                           | Timeline only                                   |
| prepared          | reserved     | `action_assign()`           | Ensures reservation; 409 OUT_OF_STOCK if cannot |
| out_for_delivery  | reserved     | `action_assign()`           | Same as prepared                                |
| delivered         | validated    | `qty_done` + `button_validate()` | On Hand decreases                       |
| cancelled         | varies       | Cancel or return            | Not validated → cancel; validated → return      |

**Delivered policy**: BLOCK partial delivery. All moves must be fully reserved before validating. Rationale: retail branches should avoid partial deliveries without explicit manager approval.

## 3) Transaction-Like Flow

`POST /api/v1/orders/<id>/delivery/status` and `POST /api/v1/driver/orders/<id>/delivery/status`:

1. Load order (sudo, with company/warehouse context)
2. Fetch outgoing pickings
3. **Precondition**: Pickings exist (except initial received)
4. Execute picking actions (assign / validate) **before** writing timeline
5. Only after success: write `mxm.order.status.log` and update `mxm_delivery_status`
6. Response: `order_id`, `order_number`, `new_status`, `picking_id`, `picking_state`, `stock_effect`

## 4) Response Fields

Success payload includes:

```json
{
  "success": true,
  "data": {
    "order_id": 123,
    "current_status": { "code": "delivered", "label": "...", "at": "..." },
    "timeline": [...],
    "picking_id": 456,
    "picking_state": "done",
    "stock_effect": "validated",
    "new_status": "delivered"
  }
}
```

`stock_effect`: `"none"` | `"reserved"` | `"validated"`

## 5) Hardening: No Fake Timeline

- Any status update (except `None → received`) requires outgoing pickings
- For `delivered`: At least one move line must be validatable
- On failure: return error, **do not** write timeline

## 6) Structured Logging

| Log Tag                  | When                                   |
|--------------------------|----------------------------------------|
| `[DELIVERY_STATUS_REQ]`  | Request: order_id, from, to, pickings  |
| `[PICKING_FOUND]`        | Pickings found or none                 |
| `[PICKING_ASSIGN]`       | After `action_assign`                  |
| `[PICKING_VALIDATE]`     | After `button_validate`                |
| `[DELIVERY_STATUS_COMMIT]` | Timeline written; order_id, status, stock_effect |

## 7) Error Codes

| Code               | HTTP | When                                         |
|--------------------|------|----------------------------------------------|
| NO_DELIVERY_PICKING| 400  | No outgoing picking for status update        |
| OUT_OF_STOCK       | 409  | Cannot reserve (prepared / out_for_delivery) |
| VALIDATION_ERROR   | 400  | Invalid transition, validation failed        |

## 8) Config / Dependencies

- **Warehouse**: Must have delivery route and outgoing picking type
- **Products**: Storable products need routes (Step 2 fallback for MXM orders)
- **Tracking**: Lot/serial is supported via standard Odoo move-line flow
- **Partial delivery**: Not allowed by default; block if reservation incomplete

## 9) Curl Verification

### A) Confirm order (customer app)

```bash
curl -s -X POST "$BASE/api/v1/mxm/orders" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"warehouse_id": 1, "items": [{"product_id": 42, "qty": 2}]}' | jq .
```

**Expected**: 200, `state: "sale"`, `picking_id` present; outgoing picking exists and is assigned.

### B) Driver sets "prepared"

```bash
curl -s -X POST "$BASE/api/v1/driver/orders/$ORDER_ID/delivery/status" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"status": "prepared"}' | jq .
```

**Expected**: 200, `stock_effect: "reserved"`, `picking_state: "assigned"`.

### C) Driver sets "delivered"

```bash
curl -s -X POST "$BASE/api/v1/driver/orders/$ORDER_ID/delivery/status" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"status": "delivered"}' | jq .
```

**Expected**: 200, `stock_effect: "validated"`, `picking_state: "done"`.

### D) On Hand decreased

After delivered:

- Inventory → Products → product 42: On Hand decreased by ordered qty
- Or via API: `GET /api/v1/mxm/products?warehouse_id=1` → `qty_on_hand` lower

### E) No picking → NO_DELIVERY_PICKING

Use an order that has no outgoing picking (e.g. service-only or misconfigured):

```bash
curl -s -X POST "$BASE/api/v1/driver/orders/$ORDER_ID/delivery/status" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"status": "preparing"}' | jq .
```

**Expected**: 400, `code: "NO_DELIVERY_PICKING"`, message: "No delivery picking found. Confirm the order to create one." Timeline unchanged.
