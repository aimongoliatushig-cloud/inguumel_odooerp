# Order lifecycle – canonical state and payment (backend)

Backend is canonical for `/api/v1/mxm/orders` (list) and `/api/v1/mxm/orders/<id>` (detail). RN UI should use these fields for stable display.

## Response fields (list and detail)

Stable contract for RN (preferred field names):

| Field | Type | Description |
|-------|------|-------------|
| `order_state_code` | string | Enum: `PENDING_MERCHANT`, `CONFIRMED`, `DELIVERED`, `CANCELLED`. |
| `order_state_label_mn` | string | Mongolian label for UI. |
| `payment_method_code` | string | Enum: `COD`, `QPAY`, `OTHER`. |
| `payment_method_label_mn` | string | Mongolian label for UI. |
| `payment_state_code` | string | Enum: `PAID`, `UNPAID`. |
| `payment_state_label_mn` | string | Mongolian label for UI. |
| `is_paid` | bool | True when payment is confirmed. |

Backward compatibility: `order_state`, `payment_method`, `payment_status`, `payment_status_label_mn`, `paid` are still returned (same values as above). Existing fields (`id`, `order_number`, `status`, `state`, `payment`, etc.) remain.

---

## Order state mapping

| Odoo `state` | `order_state_code` | `order_state_label_mn` |
|--------------|--------------------|-------------------------|
| `draft`, `sent` (quotation) | `PENDING_MERCHANT` | Хүлээгдэж байна |
| `sale` | `CONFIRMED` | Баталгаажсан |
| `done` | `DELIVERED` | Хүргэгдсэн |
| `cancel` | `CANCELLED` | Цуцалсан |

---

## Payment

### Payment method

| Raw (`x_payment_method`) | `payment_method_code` | `payment_method_label_mn` |
|--------------------------|------------------------|----------------------------|
| `cod` | `COD` | Бэлнээр |
| `qpay_pending` | `QPAY` | QPay |
| other | `OTHER` | Бусад |

### Payment state

- **COD:** `payment_state_code = UNPAID` ("Төлөгдөөгүй") until payment is confirmed; then `PAID` ("Төлөгдсөн").
- **QPay:** same: `UNPAID` / `PAID` based on `is_paid`.

| Condition | `payment_state_code` | `payment_state_label_mn` |
|-----------|----------------------|--------------------------|
| Not paid | `UNPAID` | Төлөгдөөгүй |
| Paid | `PAID` | Төлөгдсөн |

---

## Lifecycle (summary)

1. **PENDING_MERCHANT** – Order created, waiting for merchant (draft/sent).
2. **CONFIRMED** – Order confirmed (`sale`).
3. **DELIVERED** – Order delivered (`done`).
4. **CANCELLED** – Order cancelled (`cancel`).

Payment: **UNPAID** until paid, then **PAID**; `is_paid` reflects actual payment confirmation.

---

## Curl proof

After login (Bearer token in `$TOKEN`), the following show the stable contract fields.

```bash
# 1) List orders – each item has order_state_code, payment_method_code, payment_state_code, is_paid, *_label_mn
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders" | jq '.data[0] | {order_state_code, order_state_label_mn, payment_method_code, payment_method_label_mn, payment_state_code, payment_state_label_mn, is_paid}'

# 2) Order detail – full object includes the same stable fields
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders/<id>" | jq '.data | {order_state_code, order_state_label_mn, payment_method_code, payment_method_label_mn, payment_state_code, payment_state_label_mn, is_paid}'

# 3) Automated proof (checks all required fields)
BASE="${BASE:-http://127.0.0.1:8069}" PHONE=... PIN=... bash inguumel_order_mxm/scripts/curl_order_detail_label_mn.sh
```
