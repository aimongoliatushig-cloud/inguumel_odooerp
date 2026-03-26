# Delivery POS visibility + Prepaid On Hand policy

## A) Why mobile orders were not showing in Delivery POS

### Root cause

Delivery POS loads orders via **GET /api/v1/pos/online-orders** with:

- **Warehouse:** Either `warehouse_id=<id>` (query) or `config_id=<pos.config id>` (then warehouse from `pos.config.warehouse_id`).
- **Domain (backend):**  
  `[("warehouse_id", "=", wh_id), ("state", "in", ["sale", "done"]), + status filter]`.

So visibility depends on:

1. **Correct warehouse**  
   If the POS sends `config_id` and that **pos.config has no `warehouse_id`** set (e.g. “Inguumel Delivery” tab added but config not linked to a branch), the API used to return **400** “warehouse_id or config_id with warehouse is required” and the POS showed no orders.

2. **Same warehouse as mobile orders**  
   Mobile orders get `warehouse_id` from cart/checkout (request param or user/partner default). If the POS branch uses a different `warehouse_id` (or none), the domain `warehouse_id = wh_id` does not match those orders.

3. **Pending = not delivered/cancelled**  
   “Pending” uses `mxm_delivery_status` in `(False, received, preparing, prepared, out_for_delivery)`. Newly confirmed orders can have `mxm_delivery_status == False` (not yet set). The domain was updated to explicitly include unset status with an OR: `("mxm_delivery_status", "=", False) | ("mxm_delivery_status", "in", ["received", ...])`, so newly confirmed orders appear even before the first status log is written.

### Fixes applied

1. **Warehouse fallback when `config_id` has no warehouse**  
   If the request sends `config_id` but `pos.config.warehouse_id` is empty:
   - Use **first warehouse in user scope** (if warehouse owner) or **first warehouse of user’s company** (if stock user).
   - This avoids 400 and returns orders for that warehouse; a warning is logged so you can set `pos.config.warehouse_id` for the branch.

2. **Pending domain**  
   Pending filter now explicitly includes unset status:  
   `["|", ("mxm_delivery_status", "=", False), ("mxm_delivery_status", "in", ["received", "preparing", "prepared", "out_for_delivery"])]`  
   so newly confirmed mobile orders show up in Delivery POS even when `mxm_delivery_status` is not set yet.

3. **No extra field required**  
   Mobile orders are plain `sale.order` with `state in ['sale','done']`, `warehouse_id` set at checkout, and (after confirm) `mxm_delivery_status` set to `received` (or unset until first log). No `x_is_delivery` or team/carrier is required; the same domain works for both Odoo Delivery Workbench and POS API.

### Exact domain that makes orders visible (POS pending)

- `("warehouse_id", "=", <requested or fallback warehouse id>)`
- `("state", "in", ["sale", "done"])`
- For **state=pending**:  
  `["|", ("mxm_delivery_status", "=", False), ("mxm_delivery_status", "in", ["received", "preparing", "prepared", "out_for_delivery"])]`

So: **warehouse_id** (and optionally unset status for pending) is the field/domain that controls “appearing in Delivery POS”.

### Quick manual test (POS visibility)

1. **Ensure POS config has warehouse (recommended)**  
   Settings → POS → open the config used by Delivery POS → set **Салбар (Агуулах) / warehouse_id** to the branch warehouse. Then call:
   ```bash
   curl -s "$BASE/api/v1/pos/online-orders?config_id=CONFIG_ID&state=pending" \
     -H "Authorization: Bearer $TOKEN" | jq '.data | length, .[0].order_number'
   ```
   You should see at least one order if there are confirmed mobile orders for that warehouse.

2. **Or pass warehouse_id explicitly**  
   ```bash
   curl -s "$BASE/api/v1/pos/online-orders?warehouse_id=1&state=pending" \
     -H "Authorization: Bearer $TOKEN" | jq .
   ```
   Use the same `warehouse_id` the mobile app uses for checkout (e.g. from cart/checkout or user default).

3. **Confirm flow creates visible order**  
   Create draft (cart checkout) → address → confirm. Then call the same GET again; the new order should appear in `data` (same warehouse, state=sale, pending status or unset).

---

## B) Stock policy (prepaid vs COD, cancel)

Already implemented in `order_flow.py` and `sale_order.py`:

- **Prepaid** (`qpay_paid` / `card_paid` / `wallet_paid`): On confirm → validate outgoing picking (On Hand decreases immediately). Cancel → create/validate return picking(s) then cancel order (idempotent).
- **COD:** On confirm → only reserve (`action_assign`); On “delivered” → validate picking (On Hand decreases). Cancel before delivered → unreserve; cancel after delivered → same return flow as prepaid.

Manual tests: see **docs/CURL_ORDER_FLOW_STOCK_POLICY.md**.

---

## Restart / upgrade

```bash
sudo systemctl restart odoo
# or
./odoo-bin -c /etc/odoo19.conf -u inguumel_order_mxm --stop-after-init
```
