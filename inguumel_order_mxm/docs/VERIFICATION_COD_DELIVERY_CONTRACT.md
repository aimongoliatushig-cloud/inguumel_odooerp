# Verification: COD + Delivery backend contract

Copy-paste commands for InguumelStage (or local). Replace `BASE`, `ORDER_ID`, and credentials as needed.

## A) Driver delivery GET – next_actions and picking fields

```bash
BASE="https://your-odoo.example.com"   # or http://127.0.0.1:8069
ORDER_ID=42

# Driver login (X-App: driver)
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" -H "X-App: driver" \
  -d '{"phone":"<DRIVER_PHONE>","pin":"<PIN>"}')
TOKEN=$(echo "$RES" | jq -r '.data.access_token')

# GET driver delivery – must include next_actions, picking_id, picking_state, blocked_reason
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/orders/$ORDER_ID/delivery" \
  | jq '{ current_status: .data.current_status.code, next_actions: .data.next_actions, picking_id: .data.picking_id, picking_state: .data.picking_state, blocked_reason: .data.blocked_reason }'
```

**Acceptance:** For `current_status.code == "preparing"` expect `next_actions == ["prepared","cancelled"]`. For `out_for_delivery` expect `["delivered","cancelled"]`. `picking_id` number or null; `picking_state` string or null; `blocked_reason` null or `"NO_DELIVERY_PICKING"`.

## B) Cash confirm – idempotent, no invoices

```bash
BASE="https://your-odoo.example.com"
ORDER_ID=42

# Cashier login
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" \
  -d '{"phone":"<CASHIER_PHONE>","pin":"<PIN>"}')
TOKEN=$(echo "$RES" | jq -r '.data.access_token')

# First call
curl -s -X POST "$BASE/api/v1/orders/$ORDER_ID/cash-confirm" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | jq '{ message, data: .data }'

# Second call – must return already_confirmed: true, message "Already confirmed"
curl -s -X POST "$BASE/api/v1/orders/$ORDER_ID/cash-confirm" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}' | jq '.message, .data.already_confirmed'
```

**Acceptance:** First call: `data.x_paid == true`, `data.already_confirmed == false`, `data.x_cash_confirmed_at` set. Second call: `data.already_confirmed == true`, `message == "Already confirmed"`.

## C) Invoice sanity – no account.move for COD after cash-confirm

Order must be COD and confirmed via cash-confirm. Then check that no customer invoice was created for that order (invoice_origin = order name).

**JsonRPC (Odoo shell or external script):**

```python
# In Odoo shell: env from request or env.cr
order_name = "SO001"  # replace with your order name
moves = env["account.move"].search_read(
    [("invoice_origin", "=", order_name), ("move_type", "=", "out_invoice")],
    ["name", "state", "invoice_origin"]
)
assert len(moves) == 0, "COD cash-confirm must not create invoices; found: %s" % moves
```

**curl JsonRPC (replace url, db, username, password):**

```bash
BASE="https://your-odoo.example.com"
DB="InguumelStage"
USER="admin"
PASS="..."

# Get order name first (e.g. SO001)
ORDER_ID=42
ORDER_NAME=$(curl -s -X POST "$BASE/jsonrpc" -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{\"service\":\"object\",\"method\":\"execute_kw\",\"args\":[\"$DB\",2,\"$PASS\",\"sale.order\",\"read\",[[$ORDER_ID],[\"name\"]]]},\"id\":1}" | jq -r '.result[0].name')

# Search account.move by invoice_origin
curl -s -X POST "$BASE/jsonrpc" -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"method\":\"call\",\"params\":{\"service\":\"object\",\"method\":\"execute_kw\",\"args\":[\"$DB\",2,\"$PASS\",\"account.move\",\"search_read\",[[[\"invoice_origin\",\"=\",\"$ORDER_NAME\"],[\"move_type\",\"=\",\"out_invoice\"]],[\"name\",\"state\",\"invoice_origin\"]]]},\"id\":2}" | jq '.result'
```

**Acceptance:** `result` is `[]` for COD orders that were only cash-confirmed (no manual invoicing). If your flow later creates invoices by other means, this check is for “cash-confirm alone must not create invoices”.

## Summary

| Test | Expectation |
|------|-------------|
| GET delivery (preparing) | `next_actions` = `["prepared","cancelled"]` |
| GET delivery (out_for_delivery) | `next_actions` = `["delivered","cancelled"]` |
| No picking + not terminal | `blocked_reason` = `"NO_DELIVERY_PICKING"` |
| Cash-confirm 1st call | `x_paid` true, `already_confirmed` false |
| Cash-confirm 2nd call | `already_confirmed` true, no side effects |
| COD after cash-confirm | No `account.move` with invoice_origin = order name (unless created elsewhere) |
