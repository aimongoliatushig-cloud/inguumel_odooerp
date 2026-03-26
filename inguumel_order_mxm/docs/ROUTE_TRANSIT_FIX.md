# Fix: "No rule has been found to replenish ... in Transit" (MXM API orders)

## 1. Root cause

**What happens:** Customer app creates a sale order via API; on `action_confirm()` Odoo raises:  
*"No rule has been found to replenish '[SKU] ...' in 'Агуулах хоорондын хөдөлгөөн (transit)'."*

**Why:** Route selection for `sale.order.line` in Odoo comes from (in effect):

1. **Line `route_ids`** (M2M) – if set on the line, that is used for procurement.
2. **Product** – `product.route_ids` and product type.
3. **Product category** – `categ_id.route_ids` / `total_route_ids`.
4. **Warehouse** – e.g. `warehouse.delivery_route_id` when no route on line/product.

When the API creates the order it does **not** set `route_ids` on the lines. So after `create()`, the line gets its routes from **product** and/or **category**. If the product (or its category) has **MTO** (route 1) or another route that has a **stock.rule** with **destination = Transit** (e.g. rule id 7 or 8: src=WH/Нөөц → dest=Transit), then procurement tries to “replenish” in Transit. There is no rule that *replenishes* Transit from Stock in that route chain, so Odoo raises the error. So the sale order line is effectively using a route whose rule points to **location_id = Transit (10)** instead of **Customers (2)**. We want 1-step delivery: **WH/Нөөц (5) → Customers (2)** using the warehouse’s “Deliver in 1 step (ship)” route (e.g. `route_id=3`).

**Summary:** The confirmed sale order chooses a route/rule that has **dest = Transit** because the line’s `route_ids` (filled from product/category) include a route that has such a rule. Route selection “priority” in practice is: line > product > category > warehouse; and the line was empty so product/category won, leading to a transit rule.

---

## 2. Fix applied (code – minimal risk)

**Where:** `inguumel_order_mxm/models/sale_order.py` – `_mxm_ensure_delivery_routes_for_mobile()`.

**Change:**

- **Before:** Only set `line.route_ids` to `warehouse.delivery_route_id` when `line.route_ids` was **empty**, and only for **storable** lines.
- **After:** For orders with `origin` containing `"MXM"`, **always** set `line.route_ids = [warehouse.delivery_route_id]` for **storable and consumable** lines (overwrite existing route_ids). So API-created orders always use the 1-step delivery route and never use product/category routes that point to Transit/MTO.

**Why it’s safe:**

- Only runs when `"MXM" in (order.origin or "")`, so **only mobile-API-created orders** are affected. POS and standard Sales flows are unchanged.
- Uses the warehouse’s **delivery route** (e.g. “Deliver in 1 step (ship)”), which already exists and is correct for normal delivery. No new routes or rules.
- Storable and consumable lines are forced to that route; other line types (e.g. service) are skipped as before.
- No change to stock rules, locations, or other modules; only the route on the **sale order line** is set before confirmation.

**Config alternative (if you prefer no code change):**  
Remove MTO (route 1) and the inactive route (6) from **product** 3714 and from its **product category** so that no route with a rule to Transit is on the product/category. Then the line would get a route that does not use Transit. The code fix is preferred because it guarantees MXM orders always use the warehouse delivery route regardless of product/category data.

---

## 3. Verification

### A) After fix – newly created order (Odoo shell)

Replace `ORDER_ID` with a real sale order id (or create one via API then use its id).

```python
order = env['sale.order'].browse(ORDER_ID)
print("Order:", order.id, order.name, "origin:", order.origin)
for line in order.order_line:
    if not line.product_id:
        continue
    rids = line.route_ids.ids if line.route_ids else []
    print("  Line", line.id, "product_id", line.product_id.id, "route_ids", rids)
    for move in line.move_ids:
        print("    Move", move.id, "location_dest_id", move.location_dest_id.id, move.location_dest_id.complete_name)
for p in order.picking_ids:
    print("Picking", p.id, p.name, "location_dest_id", p.location_dest_id.id, p.location_dest_id.complete_name)
```

**Expected after fix:**  
- Each (storable/consu) line has `route_ids = [3]` (or your warehouse delivery route id).  
- Moves and pickings have `location_dest_id` = **Customers** (2), not Transit (10).

### B) Where route → Transit comes from (SQL)

```sql
-- Rules that have destination = Transit (adjust location_id if your Transit is different)
SELECT sr.id, sr.route_id, r.name AS route_name, r.active,
       sr.location_src_id, sl_src.name AS src_name,
       sr.location_dest_id, sl_dest.name AS dest_name
FROM stock_rule sr
JOIN stock_route r ON r.id = sr.route_id
JOIN stock_location sl_src ON sl_src.id = sr.location_src_id
JOIN stock_location sl_dest ON sl_dest.id = sr.location_dest_id
WHERE sl_dest.name ILIKE '%transit%' OR sr.location_dest_id = 10;
```

This shows which **route_id** and **stock_rule** rows have destination = Transit. The sale order line’s `route_ids` (or product/category routes) were pointing to one of these routes before the fix.

**Line route_ids (M2M):**

```sql
-- sale_order_line_stock_route_rel: line_id -> route_id
SELECT sol.id AS line_id, sol.order_id, sol.product_id, r.id AS route_id, r.name AS route_name
FROM sale_order_line sol
JOIN sale_order_line_stock_route_rel rel ON rel.order_line_id = sol.id
JOIN stock_route r ON r.id = rel.route_id
WHERE sol.order_id = ORDER_ID;
```

Replace `ORDER_ID`. After fix, you should see only the warehouse delivery route (e.g. 3) for MXM orders.

### C) After fix – confirmation and API

1. **Create order via API (curl):**

```bash
curl -s -X POST "$BASE/api/v1/mxm/orders" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"warehouse_id": 1, "items": [{"product_id": 3714, "qty": 1}]}' | jq .
```

**Expected:** HTTP 200, `success: true`, `state` confirmed; no “replenish … in Transit” error.

2. **Check picking destination (shell or SQL):**

```sql
SELECT sp.id, sp.name, sp.origin, sp.state, sl.id AS dest_loc_id, sl.complete_name AS dest_name
FROM stock_picking sp
JOIN stock_location sl ON sl.id = sp.location_dest_id
WHERE sp.origin = 'SO001'   -- use your order name
  AND sp.picking_type_id IN (SELECT id FROM stock_picking_type WHERE code = 'outgoing');
```

**Expected:** One outgoing picking with `dest_name` = **Customers** (or your customer location), not Transit.

---

## 4. Summary

- **Cause:** Line route came from product/category (MTO or route with rule to Transit). Procurement then tried to replenish in Transit and failed.
- **Fix:** For MXM-origin orders, `_mxm_ensure_delivery_routes_for_mobile()` now **overwrites** `route_ids` with the warehouse delivery route for storable and consumable lines, so confirmation always uses 1-step delivery (Stock → Customers) and never Transit.
- **Safety:** Only affects orders with `"MXM"` in `origin`; POS and standard Sales unchanged. No new routes or rules; only line route assignment is forced before confirm.
