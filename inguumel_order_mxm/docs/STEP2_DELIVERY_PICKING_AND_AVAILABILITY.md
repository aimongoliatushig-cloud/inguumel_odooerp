# Step 2: Delivery Picking and Availability (Backend)

## 1. What changed

### A) Delivery picking for mobile orders

**Problem:** Orders from the Customer App (MXM) often had no outgoing delivery picking (WH/OUT/xxxx) because order lines had empty `route_ids`, so procurement did not create stock moves/pickings.

**Fix:**

- **Helper:** `sale.order._mxm_ensure_delivery_routes_for_mobile()` in `inguumel_order_mxm/models/sale_order.py`.
  - Runs only for orders whose `origin` contains `"MXM"` (mobile-origin).
  - For each **storable** order line with **empty** `route_ids`:
    - If the order’s warehouse has a `delivery_route_id` and company matches, set `line.route_ids` to that route.
  - Does **not** overwrite existing `route_ids`; only fills when empty.
  - Logs: `[MXM_ROUTE_FALLBACK] order_id=... order_name=... line_id=... product_id=... set route_ids=[...]`

**Where it is called:**

1. **create()** – After `super().create(vals_list)`, for each new order: `order._mxm_ensure_delivery_routes_for_mobile()` so draft mobile orders have routes before they are confirmed.
2. **action_confirm()** – **Before** `super().action_confirm()`: `self._mxm_ensure_delivery_routes_for_mobile()` so when procurement runs during confirm, routes are already set. Existing `[CONFIRM_BEFORE]` diagnostics are unchanged.

### B) Reserve stock right after confirmation

- After `super().action_confirm()` and after the guard (storable + no outgoing picking → UserError):
  - For each outgoing picking, `picking.action_assign()` is called (if state is `confirmed` or `waiting`).
  - This reduces **free_qty** immediately and prevents oversell.
  - No validation/delivery here; only reservation.
- Logs: `[RESERVE] order_id=... order_name=... picking_id=... picking_name=... assigned=True/False state=...`

### C) Product availability API (branch visibility)

**File:** `inguumel_catalog_mxm/controllers/products.py`

**GET /api/v1/mxm/products?warehouse_id=&lt;id&gt;** returns per product:

| Field          | Meaning                          | Use |
|----------------|----------------------------------|-----|
| `qty_on_hand`  | Physical quantity in warehouse  | Stock level |
| `qty_reserved` | Reserved quantity               | Committed |
| `qty_free`     | On hand − reserved              | Available to promise |
| `qty_forecast` | Forecast (virtual_available)    | Future availability |
| `available_qty`| **MUST equal qty_free**         | Same as qty_free (API contract) |

So the app can show “available” = free after reservation; free decreases when orders are confirmed and reserved.

### D) No changes in Step 2

- No mobile app/UI changes.
- No auto-validate of pickings on confirm.
- No Step 3 delivery status mapping changes.
- No partial delivery logic.

---

## 2. Logs to watch

For a successful mobile order create/confirm:

```
[CONFIRM_BEFORE] order_id=... order_name=... state=draft ... warehouse_outgoing_ok=... lines=... pickings_count=0 outgoing_count=0
[MXM_ROUTE_FALLBACK] order_id=... order_name=... line_id=... product_id=... set route_ids=[...]
[CONFIRM_AFTER] order_id=... order_name=... state=sale ... outgoing_count=1
[RESERVE] order_id=... order_name=... picking_id=... picking_name=... assigned=True state=assigned
```

If routes were already set, `[MXM_ROUTE_FALLBACK]` may not appear. If stock is insufficient, `assigned=False` and `state=confirmed` (or similar); reservation still attempted and logged.

---

## 3. Curl tests (mandatory)

Use real `$BASE`, `$TOKEN`, `$ORDER_ID`, and product id (e.g. `42`) as needed.

### 1) Upgrade and restart

```bash
sudo systemctl restart odoo
# Or upgrade:
# ./odoo-bin -c odoo.conf -d <db> -u inguumel_order_mxm,inguumel_catalog_mxm --stop-after-init
```

### 2) Smoke test – create mobile order and verify picking

**A) Create/confirm order (mobile API path)**

```bash
curl -s -X POST "$BASE/api/v1/mxm/orders" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"warehouse_id": 1, "items": [{"product_id": 42, "qty": 2}]}' | jq .
```

**Expected:**

- Response `success: true`; order confirmed (e.g. `state: "sale"` or equivalent).
- Logs: `[MXM_ROUTE_FALLBACK]` if routes were missing; `[CONFIRM_AFTER]` with `outgoing_count >= 1`; `[RESERVE]` with picking state e.g. `assigned` (if stock exists).

**B) Order has outgoing picking**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/v1/mxm/orders/$ORDER_ID" | jq '.data | {order_number, state, delivery_picking_id, picking_ids}'
```

**Expected:** `delivery_picking_id` or `picking_ids` non-empty; `state` is sale (or your system’s confirmed state).

**C) Product availability (free decreased)**

```bash
curl -s -H "Authorization: Bearer $TOKEN" \
  "$BASE/api/v1/mxm/products?warehouse_id=1" | \
  jq '.data[] | select(.id==42) | {id, qty_on_hand, qty_reserved, qty_free, qty_forecast, available_qty}'
```

**Expected:**

- After confirm/reserve: `qty_reserved` increased, `qty_free` decreased.
- `available_qty` equals `qty_free`.
- `qty_on_hand` may be unchanged until delivery is validated (expected).

### 3) UI check in Odoo

- Open the Sales Order (e.g. Sxxxxx), confirm it exists and is confirmed.
- Go to **Inventory → Warehouse → Deliveries**.

**Expected:** A WH/OUT picking exists for that sales order and appears in the delivery list; it can be processed.

---

## 4. Summary

- **Delivery picking:** Mobile orders get delivery routes (when empty) in `create()` and **before** `action_confirm()`, so native procurement creates WH/OUT pickings.
- **Reservation:** Outgoing pickings are reserved (`action_assign()`) right after confirm so free qty decreases and oversell is avoided.
- **Products API:** `qty_on_hand`, `qty_reserved`, `qty_free`, `qty_forecast`, and `available_qty` (= `qty_free`) are exposed for branch visibility.

Step 2 is complete and ready for Step 3.
