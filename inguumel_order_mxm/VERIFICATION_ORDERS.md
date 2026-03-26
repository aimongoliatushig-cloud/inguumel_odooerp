# Order Bugs Fix – Root Cause, Diffs, Verification

## Root cause summary

### A) Mobile app shows order as "paid" immediately for COD
- **Cause**: `/api/v1/mxm/order/create` response did not include `paid` or `payment_status`. Client likely defaulted to "paid" or inferred from `invoice_status`/state.
- **Fix**: Response now includes `paid: false`, `payment_status: "cod_pending"` (for COD) or `"unpaid"`, and `payment_method`. Do not map `invoice_status` "to invoice" as paid.

### B) "My Orders" list does not show created orders
- **Cause**: No "My Orders" API existed; only POST `/api/v1/mxm/orders` (legacy create) and POST `/api/v1/mxm/order/create` (cart-based create).
- **Fix**: Added GET `/api/v1/mxm/orders` that filters `sale.order` by `request.env.user.partner_id.id` (and optional `warehouse_id`). Returns S00004/S00005 for partner_id=11.

### C) WAREHOUSE_REQUIRED when warehouse_id in query string
- **Cause**: Controller read `warehouse_id` only from JSON body (`payload.get("warehouse_id")`). Query params are in `kwargs` for the route.
- **Fix**: Read `warehouse_id` from `kwargs.get("warehouse_id")` first, then `payload.get("warehouse_id")`, then fallback to cart's warehouse.

---

## Code diffs

### 1. `inguumel_order_mxm/controllers/order_create.py`

**Lines 106–112** – warehouse_id from query then body:
```diff
-            # warehouse_id: from payload, or fallback to cart's warehouse
-            warehouse_id = payload.get("warehouse_id")
+            # warehouse_id: from query params first, then JSON body, then fallback to cart
+            warehouse_id = kwargs.get("warehouse_id")
+            if warehouse_id is None or warehouse_id == "":
+                warehouse_id = payload.get("warehouse_id")
             cart = None
```

**Lines 168–186** – payment status in create response:
```diff
             status = "created" if order.state == "sale" else "draft"
+            payment_method = getattr(order, "x_payment_method", None) or "cod"
+            # Do not map invoice_status 'to invoice' as paid; COD is always unpaid at creation
+            paid = False
+            payment_status = "cod_pending" if payment_method == "cod" else "unpaid"
             return ok(
                 data={
                     "order_id": order.id,
                     "order_number": order.name,
                     "status": status,
+                    "paid": paid,
+                    "payment_status": payment_status,
+                    "payment_method": payment_method,
                 },
                 request_id=request_id,
             )
```

### 2. `inguumel_order_mxm/controllers/order_list.py` (new file)

- New controller: GET `/api/v1/mxm/orders`.
- Filters: `partner_id = request.env.user.partner_id.id`, optional `warehouse_id` query.
- Ordering: `date_order desc, id desc`.
- Response items: `order_id`, `order_number`, `status`, `paid`, `payment_status`, `payment_method`, `partner_id`, `amount_total`, `date_order`.
- Payment contract: `paid: false`, `payment_status: "cod_pending"` for COD, `"unpaid"` otherwise.

### 3. `inguumel_order_mxm/controllers/__init__.py`

```diff
  from . import orders
  from . import order_create
+ from . import order_list
```

### 4. `inguumel_order_mxm/CURL_ORDER_CREATE.md`

- Documented: warehouse_id from query and body.
- Documented: create response fields `paid`, `payment_status`, `payment_method`.
- Documented: GET /api/v1/mxm/orders (My Orders) and expected JSON.

---

## Verification commands

Assume cookie at `/tmp/mxm_cookies.txt` (login first). `BASE="http://127.0.0.1:8069"`.

### 1. Create order with warehouse_id in query string

```bash
# Ensure cart has items for warehouse 1
curl -s -b /tmp/mxm_cookies.txt "$BASE/api/v1/mxm/cart?warehouse_id=1" | jq .
curl -s -b /tmp/mxm_cookies.txt -X POST "$BASE/api/v1/mxm/cart/lines" \
  -H "Content-Type: application/json" -d '{"product_id":7,"qty":1,"warehouse_id":1}' | jq .

# Create order – warehouse_id in query
curl -s -b /tmp/mxm_cookies.txt -X POST "$BASE/api/v1/mxm/order/create?warehouse_id=1" \
  -H "Content-Type: application/json" \
  -d '{"phone_primary":"99112233","delivery_address":"Test address"}' | jq .
```

**Expected**: `success: true`, `data.order_number` (e.g. S00006), `data.paid: false`, `data.payment_status: "cod_pending"`, `data.payment_method: "cod"`. No WAREHOUSE_REQUIRED.

### 2. Create order with warehouse_id in JSON body

```bash
curl -s -b /tmp/mxm_cookies.txt -X POST "$BASE/api/v1/mxm/order/create" \
  -H "Content-Type: application/json" \
  -d '{"phone_primary":"99112233","delivery_address":"Test address","warehouse_id":1}' | jq .
```

**Expected**: Same as above; success, paid false, payment_status cod_pending.

### 3. My Orders – list shows created orders (e.g. S00004, S00005 for partner_id=11)

```bash
curl -s -b /tmp/mxm_cookies.txt "$BASE/api/v1/mxm/orders" | jq .
```

**Expected**:
- `success: true`
- `data`: array of orders with `order_number` (S00004, S00005, …), `status: "sale"`, `paid: false`, `payment_status: "cod_pending"`, `partner_id: 11` (for that user)
- `meta.count`, `meta.total`, `meta.limit`, `meta.offset`

### 4. My Orders with warehouse filter

```bash
curl -s -b /tmp/mxm_cookies.txt "$BASE/api/v1/mxm/orders?warehouse_id=1&limit=20&offset=0" | jq .
```

**Expected**: Same shape; only orders for that partner and warehouse_id=1.

---

## Expected JSON response fields (stable)

### POST /api/v1/mxm/order/create (success)

| Field           | Type    | Description                    |
|----------------|--------|--------------------------------|
| order_id       | int    | sale.order id                  |
| order_number   | string | e.g. S00004, S00005            |
| status         | string | "created" or "draft"           |
| paid           | bool   | false for COD / to-invoice    |
| payment_status | string | "cod_pending" or "unpaid"      |
| payment_method | string | "cod" or "qpay_pending"       |

### GET /api/v1/mxm/orders (success)

| Field           | Type    | Description                    |
|----------------|--------|--------------------------------|
| data           | array  | List of order objects          |
| data[].order_id       | int    | sale.order id          |
| data[].order_number   | string | e.g. S00004, S00005    |
| data[].status         | string | "sale", "draft", etc.  |
| data[].paid           | bool   | false for COD/to-invoice |
| data[].payment_status | string | "cod_pending" or "unpaid" |
| data[].payment_method | string | "cod" or "qpay_pending" |
| data[].partner_id     | int    | res.partner id        |
| data[].amount_total   | float  | order total           |
| data[].date_order     | string | ISO datetime          |
| meta.count     | int    | length of data         |
| meta.total     | int    | total matching orders |
| meta.limit     | int    | limit used            |
| meta.offset    | int    | offset used           |
