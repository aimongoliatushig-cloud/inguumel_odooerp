# Place Order API – curl examples

## Endpoint

**POST** `/api/v1/mxm/order/create`

Requires: logged-in session (cookie), non-empty cart, warehouse selected.

## Request body (JSON)

| Field             | Type   | Required | Description                              |
|-------------------|--------|----------|------------------------------------------|
| phone_primary     | string | Yes      | Primary phone → partner.phone            |
| phone_secondary   | string | No       | Secondary phone → partner.x_phone_2      |
| delivery_address  | string | Yes      | Delivery address → order note + street   |
| warehouse_id      | int    | No*      | Warehouse. Accepted from **query** (`?warehouse_id=1`) or **JSON body**. Falls back to cart's warehouse if omitted. |
| payment_method    | string | No       | `"cod"` or `"qpay_pending"` (default: cod) |

## Response (success)

```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "request_id": "uuid",
  "data": {
    "order_id": 123,
    "order_number": "S00005",
    "status": "created",
    "paid": false,
    "payment_status": "cod_pending",
    "payment_method": "cod"
  },
  "meta": null
}
```

- `order_number`: e.g. S00004, S00005 (Odoo sequence, not SO-prefix).
- `status`: `"created"` = confirmed, `"draft"` = draft (if `mxm_order.auto_confirm` = false).
- `paid`: always `false` for COD / to-invoice; do not map invoice_status as paid.
- `payment_status`: `"cod_pending"` for COD, `"unpaid"` for qpay_pending.
- `payment_method`: `"cod"` or `"qpay_pending"`.

## Error codes

| Code               | HTTP | Description                    |
|--------------------|------|--------------------------------|
| UNAUTHORIZED       | 401  | Not logged in                  |
| PHONE_REQUIRED     | 400  | phone_primary missing          |
| ADDRESS_REQUIRED   | 400  | delivery_address missing       |
| WAREHOUSE_REQUIRED | 400  | warehouse_id missing/invalid   |
| CART_EMPTY         | 400  | Cart has no lines              |
| VALIDATION_ERROR   | 400  | payment_method or other invalid|
| SERVICE_UNAVAILABLE| 503  | Kill-switch enabled            |

## Config parameters

- `api_disabled:/api/v1/mxm/order/create` = "1"/"true" → 503
- `mxm_order.auto_confirm` = "0"/"false" → orders stay draft
- `mxm_order.update_partner_last_used` = "1" (default) → update partner phone/address; "0" → do not touch partner

## Curl tests (full flow)

```bash
BASE="http://127.0.0.1:8069"

# 1) Login (store cookie)
curl -s -c /tmp/mxm_cookies.txt -H "Content-Type: application/json" \
  -d '{"phone":"95909912","pin":"050206"}' "$BASE/api/v1/auth/login"
# Expect: success true

# 2) GET /api/v1/auth/me (prefill data for RN form)
curl -s -b /tmp/mxm_cookies.txt "$BASE/api/v1/auth/me" | jq .
# Expect: success true, data.phone_primary, data.delivery_address, etc.

# 3) Add cart line
curl -s -b /tmp/mxm_cookies.txt -X POST "$BASE/api/v1/mxm/cart/lines" \
  -H "Content-Type: application/json" \
  -d '{"product_id":5,"qty":1,"warehouse_id":2}'
# Expect: success true, cart has items

# 4) Place order
curl -s -b /tmp/mxm_cookies.txt -X POST "$BASE/api/v1/mxm/order/create" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_primary": "99112233",
    "phone_secondary": "88112233",
    "delivery_address": "Хэрлэн сум, 5-р баг, 12-34",
    "warehouse_id": 2,
    "payment_method": "qpay_pending"
  }' | jq .
# Expect: success true, data.order_id, data.order_number, data.status

# 5) Verify cart cleared
curl -s -b /tmp/mxm_cookies.txt "$BASE/api/v1/mxm/cart?warehouse_id=2" | jq .
# Expect: items empty, total_qty 0
```

## Error tests

```bash
# PHONE_REQUIRED (omit phone_primary)
curl -s -b /tmp/mxm_cookies.txt -X POST "$BASE/api/v1/mxm/order/create" \
  -H "Content-Type: application/json" \
  -d '{"delivery_address":"Test","warehouse_id":2}'

# ADDRESS_REQUIRED (omit delivery_address)
curl -s -b /tmp/mxm_cookies.txt -X POST "$BASE/api/v1/mxm/order/create" \
  -H "Content-Type: application/json" \
  -d '{"phone_primary":"99112233","warehouse_id":2}'

# CART_EMPTY (clear cart first, then place order)
curl -s -b /tmp/mxm_cookies.txt -X DELETE "$BASE/api/v1/mxm/cart?warehouse_id=2"
curl -s -b /tmp/mxm_cookies.txt -X POST "$BASE/api/v1/mxm/order/create" \
  -H "Content-Type: application/json" \
  -d '{"phone_primary":"99112233","delivery_address":"Test","warehouse_id":2}'
```

---

## warehouse_id: query string OR JSON body

Create works with `warehouse_id` in **query** or **body** (body overrides if both sent).

```bash
# A) warehouse_id in query string
curl -s -b /tmp/mxm_cookies.txt -X POST "$BASE/api/v1/mxm/order/create?warehouse_id=1" \
  -H "Content-Type: application/json" \
  -d '{"phone_primary":"99112233","delivery_address":"Test address"}' | jq .

# B) warehouse_id in JSON body
curl -s -b /tmp/mxm_cookies.txt -X POST "$BASE/api/v1/mxm/order/create" \
  -H "Content-Type: application/json" \
  -d '{"phone_primary":"99112233","delivery_address":"Test address","warehouse_id":1}' | jq .
```

---

## My Orders – GET /api/v1/mxm/orders

List sale orders for the logged-in user's partner (e.g. partner_id=11 shows S00004, S00005).

```bash
curl -s -b /tmp/mxm_cookies.txt "$BASE/api/v1/mxm/orders" | jq .
curl -s -b /tmp/mxm_cookies.txt "$BASE/api/v1/mxm/orders?warehouse_id=1&limit=20&offset=0" | jq .
```

**Expected response (success):**

```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "request_id": "uuid",
  "data": [
    {
      "order_id": 5,
      "order_number": "S00005",
      "status": "sale",
      "paid": false,
      "payment_status": "cod_pending",
      "payment_method": "cod",
      "partner_id": 11,
      "amount_total": 15000.0,
      "date_order": "2026-02-01 12:00:00"
    },
    {
      "order_id": 4,
      "order_number": "S00004",
      "status": "sale",
      "paid": false,
      "payment_status": "cod_pending",
      "payment_method": "cod",
      "partner_id": 11,
      "amount_total": 12000.0,
      "date_order": "2026-02-01 11:00:00"
    }
  ],
  "meta": {
    "count": 2,
    "total": 2,
    "limit": 20,
    "offset": 0
  }
}
```

Stable field names: `order_id`, `order_number`, `status`, `paid`, `payment_status`, `payment_method`, `partner_id`, `amount_total`, `date_order`.

---

## Order Detail – GET /api/v1/mxm/orders/<order_id>

Single order with lines, warehouse, shipping, amounts. Auth required; only the order owner (order.partner_id == user.partner_id) can read. Otherwise 404 NOT_FOUND.

**Canonical rules:**
- Warehouse: from `sale.order.warehouse_id` (never from picking).
- Shipping address: from `sale.order.x_delivery_address`; if empty, fallback to partner address fields.

### Test 1: Valid – owner user can fetch

```bash
# 1) Login as owner (partner_id=11)
curl -s -c /tmp/mxm_cookies.txt -H "Content-Type: application/json" \
  -d '{"phone":"+97699112233","pin":"YOUR_PIN"}' "$BASE/api/v1/auth/login"

# 2) List orders to get an order_id (e.g. 5)
curl -s -b /tmp/mxm_cookies.txt "$BASE/api/v1/mxm/orders" | jq '.data[0].order_id'

# 3) Fetch detail (replace 5 with actual order_id)
curl -s -b /tmp/mxm_cookies.txt "$BASE/api/v1/mxm/orders/5" | jq .
```

**Expected:** HTTP 200, `success: true`, `data` with `id`, `order_number`, `date_order`, `status`, `currency`, `warehouse`, `amounts`, `partner`, `shipping`, `payment`, `lines[]`.

### Test 2: Invalid – another user cannot fetch (404)

```bash
# Login as user A, get A's order_id. Then login as user B (different partner).
# As user B, GET /api/v1/mxm/orders/<A's_order_id>
# Expected: HTTP 404, success: false, code: "NOT_FOUND"
curl -s -b /tmp/mxm_cookies.txt "$BASE/api/v1/mxm/orders/99999" | jq .
# If 99999 is not your order: 404 NOT_FOUND
```

**Expected:** HTTP 404, `success: false`, `code: "NOT_FOUND"`, `message: "Order not found"`.

### Example response (success)

```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "request_id": "uuid",
    "data": {
    "id": 5,
    "order_number": "S00005",
    "date_order": "2026-02-01T12:00:00",
    "status": "sale",
    "currency": "MNT",
    "amount_total": 15000.0,
    "warehouse": { "id": 1, "name": "My Company" },
    "amounts": { "total": 15000.0, "untaxed": 13500.0, "tax": 1500.0 },
    "partner": { "id": 11, "name": "Customer", "phone": "99112233" },
    "shipping": {
      "address_text": "Хэрлэн сум, 5-р баг",
      "phone_primary": "99112233",
      "phone_secondary": "88112233"
    },
    "payment": {
      "payment_method": "cod",
      "payment_status": "cod_pending",
      "paid": false
    },
    "lines": [
      {
        "id": 10,
        "product_id": 7,
        "product_name": "Product A",
        "qty": 2,
        "uom": "Units",
        "price_unit": 5000,
        "discount": 0,
        "subtotal": 10000,
        "tax_amount": 1000,
        "image_url": "http://host:8069/api/v1/mxm/product-image/7?size=512&v=..."
      }
    ]
  },
  "meta": null
}
```

No crash for draft orders or orders without `x_delivery_address` (fallback to partner address).

**Client mapping (Order Detail total):** Use `data.amount_total ?? data.amounts?.total ?? 0` so list and detail both work. Format: `formatMnt(n) => typeof n === 'number' ? n.toLocaleString('en-US') + ' ₮' : '0 ₮'`. Never show "— ₮"; if amount missing show "0 ₮" and optional warning "Дүн олдсонгүй". **Warehouse:** Optional in UI; backend still returns `warehouse` but client can hide "Агуулах" section.
