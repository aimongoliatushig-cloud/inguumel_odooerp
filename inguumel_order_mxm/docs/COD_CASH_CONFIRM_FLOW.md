# COD-Only Strict Flow (Driver ≠ Paid) – Final Decision

**COD cash-confirm is operational only:** It sets `x_paid`, `x_cash_confirmed_at`, `x_cash_confirmed_by` on the sale order. It does **not** create or post invoices, and does **not** register payments. No dependency on the `account` module.

## Goals

- **Driver** only confirms delivery (no Paid/Cash actions).
- **Cashier** confirms cash (Paid) explicitly via Cash Confirm.
- **No** automatic COD-as-paid based on delivery.

---

## Backend Rules (A–E)

### A) Disable auto-paid cron

- Keep **ir.cron** “COD: Auto-paid when delivered” (e.g. id=30) **disabled** in Stage/Prod.
- Keep other standard crons **enabled** (Account auto_post, vacuum, send invoices, etc.).
- Keep config param **`inguumel.cod_auto_paid_enabled` = `false`** (default in module).

### B) Source of truth for COD paid

- **`sale.order.x_paid`** is the only paid flag used by the COD flow.
- **`x_payment_method`** stays `'cod'` for COD orders.
- Cash confirmation must set:
  - `x_paid = True`
  - `x_cash_confirmed_by` = current user
  - `x_cash_confirmed_at` = now

### C) Cash confirm endpoint

**`POST /api/v1/orders/<id>/cash-confirm`**

- **Permission:** Only users in group **“Inguumel Order / Cash Confirm (Cashier)”** or **Administrator**.
- **Validation:**
  1. Order exists
  2. Order is COD (`x_payment_method == 'cod'`)
  3. Order is delivered (`mxm_delivery_status == 'delivered'`)
- **Idempotency:** If `x_cash_confirmed_at` (or `x_paid`) already set → return **200 OK** with `{ already_confirmed: true }` (do **not** return 400).
- **On success:** Write the fields above; if `inguumel_lucky_wheel` is installed, recompute accumulated for (partner, warehouse_id).

### D) POS online orders endpoint

**`GET /api/v1/pos/online-orders`**

- Response includes: `x_paid`, `is_delivered`, `can_cash_confirm`, `x_cash_confirmed_at`, `x_cash_confirmed_by`.
- **`can_cash_confirm`** = (COD + delivered + not `x_paid`) **AND** current user has cashier permission (Cash Confirm group or Administrator).

### E) Lucky Wheel rule (unchanged)

- Count orders only when **delivered AND paid** (`x_paid` True), not based on delivery alone.

---

## Configuration

- **Kill switch:** `api_disabled:/api/v1/orders/cash-confirm` = `1` or `true` disables the cash-confirm API.
- **COD auto-paid:** Must be off for this flow: `inguumel.cod_auto_paid_enabled` = `false`; cron “COD: Auto-paid when delivered” inactive.

---

## curl examples

```bash
# Cash confirm (cashier/manager token)
curl -X POST "https://your-odoo/api/v1/orders/42/cash-confirm" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

- **First confirm:** 200, `data.x_paid: true`, `data.already_confirmed: false`, `data.x_cash_confirmed_by`, `data.x_cash_confirmed_at`.
- **Repeat (idempotent):** 200, `data.already_confirmed: true`.

---

## COD cash-confirm is operational only (no accounting automation)

**STRICT:** Cash confirm does **not** create or post invoices, and does **not** register payments. It does **not** touch `account.move` or `account.payment`. There is no dependency on the `account` module for COD.

- **Source of truth for COD paid:** `sale.order.x_paid` is the only truth. Mobile and ERP must not rely on invoice `payment_state` to decide whether a COD order is paid.
- **Idempotency:** If `x_cash_confirmed_at` is already set, the API returns HTTP 200 with `data.already_confirmed = true` and performs no side effects.

### Response shape

`data` = `{ order_id, order_number, x_paid, already_confirmed, x_cash_confirmed_by, x_cash_confirmed_at }`.

### Verification curls

```bash
BASE="http://127.0.0.1:8069"
# Login as cashier (user with Cash Confirm group)
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" \
  -d '{"phone":"<CASHIER_PHONE>","pin":"<PIN>"}')
TOKEN=$(echo "$RES" | jq -r '.data.access_token')

# 1) First call: cash confirm (order must be COD + delivered)
curl -s -X POST "$BASE/api/v1/orders/<ORDER_ID>/cash-confirm" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | jq '.data'
# Expect: already_confirmed: false, x_paid: true, x_cash_confirmed_at set

# 2) Second call (idempotency)
curl -s -X POST "$BASE/api/v1/orders/<ORDER_ID>/cash-confirm" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | jq '.data.already_confirmed, .message'
# Expect: already_confirmed: true, message: "Already confirmed"
```

### Impacted models / rollback

- **Models:** `sale.order` only (x_paid, x_cash_confirmed_at, x_cash_confirmed_by); optionally `lucky.wheel.spend` recompute when module is installed.
- **Rollback:** Set `x_paid=false`, `x_cash_confirmed_at=NULL`, `x_cash_confirmed_by=NULL` on the order. No invoice or payment to undo.
