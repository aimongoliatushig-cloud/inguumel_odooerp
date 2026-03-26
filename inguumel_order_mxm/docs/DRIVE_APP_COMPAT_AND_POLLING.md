# Drive App – Contract, Compatibility & Polling

Short reference for **order detail** and **delivery** contracts used by the Drive app, including optional alias and polling via `version`.

---

## 1. Order detail – GET /api/v1/mxm/orders/<id> (and driver variant)

**Contract:** The response `data` object **always** includes the following keys (no key missing by state).

| Key | Type | Description |
|-----|------|-------------|
| `lines` | array | Order lines (items). Always present; may be empty `[]`. |
| `order_line` | array | **Alias:** same array as `lines`. For older clients; do not rely on removal. |
| `partner` | object | `{ id, name, phone }` – customer partner |
| `shipping` | object | `{ address_text, phone_primary, phone_secondary }` |
| `amount_total` | number | Order total |
| `amounts` | object | `{ total, untaxed, tax }` – all numbers (default 0.0 if missing) |
| `currency` | string | Always `"MNT"` |

Other keys (e.g. `id`, `order_number`, `date_order`, `state`, `warehouse`, `payment`, `status_history`) are also always present. Lines are built from **sale.order.order_line**; each item includes `product_id`, `product_name`, `qty`, `uom`, `price_unit`, `discount`, `subtotal`, `tax_amount`, `image_url`. All API error responses and exception logs include **request_id** for tracing.

---

## 2. Delivery – GET /api/v1/orders/<id>/delivery (and driver variant)

**Polling:** The response `data` includes **`version`** (monotonic, e.g. last log id). Client can poll and send `?version=<previous_version>`; if backend supports it, it may return 304 or a short response when unchanged. At minimum, client can compare `data.version` with previous value to skip UI updates when equal.

**Timeline:** Each timeline item includes `code`, `label`, `at`, `is_current`, `note`. If the log has a **`source`** (system / staff / mobile_owner / etc.), the item also includes **`source`** (added key only; existing keys unchanged).

---

## 3. Optional: product image auth

**GET /api/v1/mxm/product-image/<product_id>** is **public** by default (no Bearer required).  
If the client sends **`?auth=1`**, the backend **requires** a valid Bearer token; otherwise 401. This does not change behavior when `auth=1` is not sent (mobile customer app unchanged).

---

## 4. Curl examples

**Example 1 – Order detail contains `lines` and `order_line`:**

```bash
BASE="http://72.62.247.95:8069"
# Obtain TOKEN via POST /api/v1/auth/login (phone + pin)
TOKEN="<access_token>"
ORDER_ID=5

curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders/$ORDER_ID" | jq '{
  lines: .data.lines,
  order_line: .data.order_line,
  partner: .data.partner,
  shipping: .data.shipping,
  amount_total: .data.amount_total,
  amounts: .data.amounts,
  currency: .data.currency
}'
```

Expected: `lines` and `order_line` are the same array; `partner`, `shipping`, `amount_total`, `amounts`, and `currency` are present.

**Example 2 – Delivery response contains `version` for polling:**

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/orders/$ORDER_ID/delivery" | jq '{
  order_id: .data.order_id,
  version: .data.version,
  current_status: .data.current_status,
  timeline_count: (.data.timeline | length)
}'
```

Expected: `data.version` is a number (e.g. log id); client can store it and compare on next poll to detect changes.

---

## 5. Verification curl commands

Use these to verify the Drive app contract and auth behaviour. Set `BASE`, `TOKEN` (from `POST /api/v1/auth/login`), and `ORDER_ID` / `PRODUCT_ID` as needed.

**A) Order detail – lines, order_line, partner, shipping, amounts, currency**

```bash
BASE="http://72.62.247.95:8069"
TOKEN="<access_token>"
ORDER_ID=5

curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders/$ORDER_ID" | jq '
  .success,
  (.data.lines | type),
  (.data.order_line | type),
  .data.partner,
  .data.shipping,
  .data.amount_total,
  .data.amounts,
  .data.currency
'
# Expect: success true; lines/order_line "array"; partner/shipping objects; amount_total number; amounts.total/untaxed/tax numbers; currency "MNT"
```

**B) Delivery – version, current_status.code, timeline, timeline[].source when present**

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/orders/$ORDER_ID/delivery" | jq '
  .success,
  .data.version,
  .data.current_status.code,
  (.data.timeline | length),
  [.data.timeline[] | select(has("source")) | .source]
'
# Expect: success true; version (int); current_status.code string; timeline array; list of source values where present
```

**C) Product image – auth=1 requires Bearer; no token → 401**

```bash
PRODUCT_ID=1

# Without token: expect 401
curl -s -o /dev/null -w "%{http_code}" "$BASE/api/v1/mxm/product-image/$PRODUCT_ID?auth=1"
# Expect: 401

# With token: expect 200 (or 404 if product has no image)
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/product-image/$PRODUCT_ID?auth=1"
# Expect: 200 or 404
```

---

## 6. Verification checklist

| Check | Status |
|-------|--------|
| **Order detail** – GET /api/v1/mxm/orders/<id> returns `data.lines` (array), `data.order_line` (array), `data.partner`, `data.shipping`, `data.amount_total` (number), `data.amounts` (total/untaxed/tax numbers), `data.currency` == "MNT" | Pass (contract enforced in `_order_to_detail`) |
| **Delivery** – GET /api/v1/orders/<id>/delivery returns `data.version` (int), `data.current_status.code`, `data.timeline` (array); timeline entries include `source` when log has source | Pass (payload in `_delivery_payload`) |
| **Product image** – GET .../product-image/<id>?auth=1 without Bearer → 401; with Bearer → 200/404 | Pass (auth gate in catalog images controller) |
| **Warehouse scope** – MXM order detail: warehouse_owner only sees orders where `order_in_warehouse_scope(order, user)` | Pass (order_list.get_order) |
| **Warehouse scope** – Delivery GET/POST: same scope (warehouse_owner must have order in assigned warehouses, else 403) | Pass (delivery + driver controllers) |
| **request_id** – All error responses and exception logs for these endpoints include request_id | Pass (order_list, delivery, product_image) |
