# Mobile auth and Cart API – curl examples

Login uses `request.session.authenticate(env, credential)` with `credential = {'login': user.login, 'password': pin_str, 'type': 'password'}`. Odoo then saves the session and sets the **session_id** cookie in post_dispatch.

## Exact curl commands to verify

### 1. POST /api/v1/auth/login (phone + pin) → saves cookies

```bash
curl -s -c cookies.txt -X POST "http://localhost:8069/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"99123456","pin":"123456"}'
```

- Expected: `200 OK`, body `{"success": true, "data": {"uid": <id>, "partner_id": <id>}, ...}` and **Set-Cookie: session_id=...** (stored in `cookies.txt`).

### 2. GET /web/session/get_session_info → uid not null

```bash
curl -s -b cookies.txt "http://localhost:8069/web/session/get_session_info"
```

- Expected: JSON with `"uid": <user_id>` (not null). If `uid` is null, the session cookie was not sent or the session was not authenticated.

### 3. GET /api/v1/mxm/cart?warehouse_id=2 → 200

```bash
curl -s -b cookies.txt "http://localhost:8069/api/v1/mxm/cart?warehouse_id=2"
```

- Expected: `200 OK` with cart payload (not 401).

---

## Full flow (register first if needed)

**Register** (creates partner + portal user):

```bash
curl -s -X POST "http://localhost:8069/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"phone":"99123456","pin":"123456","pin_confirm":"123456"}'
```

Then run steps 1–3 above. Replace `localhost:8069` with your Odoo base URL and `warehouse_id=2` with a valid warehouse for the user.

---

## Login flow: staff vs customer

`POST /api/v1/auth/login` supports **staff users** (Settings → Users) and **mobile customers** (partner + phone + x_pin_hash).

### 1. Staff user login (login = phone)

Create a user in Settings → Users with `login = phone` (e.g. `99123456`) and a 6-digit password. Login with phone + pin (pin = password):

```bash
curl -s -X POST "http://localhost:8069/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"99123456","pin":"123456"}'
```

- Expected: `200 OK`, `{"success": true, "data": {"uid": ..., "partner_id": ..., "access_token": ..., "role": "customer"|"warehouse_owner", ...}}`
- Staff flow: matched via `user_login` or `user_partner_phone`; no partner.x_pin_hash required.

### 2. Partner-only customer login

Use a partner created by `/auth/register` (has phone + x_pin_hash):

```bash
# Register first
curl -s -X POST "http://localhost:8069/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"phone":"99112233","pin":"654321","pin_confirm":"654321"}'
# Then login
curl -s -X POST "http://localhost:8069/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"99112233","pin":"654321"}'
```

- Expected: `200 OK` with `uid`, `partner_id`, `access_token`, `role`, etc.
- Customer flow: matched via `partner` (phone + x_pin_hash).

### 3. Wrong PIN → INVALID_PIN (staff)

Identity matched via user_login/user_partner_phone/user_partner_mobile, but password wrong:

```bash
# Staff user login=99123456 with wrong pin (password)
curl -s -X POST "http://localhost:8069/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"99123456","pin":"000000"}'
```

- Expected: `401`, `{"success": false, "code": "INVALID_PIN", "message": "Invalid credentials", ...}`

### 4. Wrong PIN → INVALID_PIN (customer)

Identity matched via partner, but pin hash mismatch:

```bash
# Use registered phone with wrong pin
curl -s -X POST "http://localhost:8069/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"99112233","pin":"000000"}'
```

- Expected: `401`, `{"success": false, "code": "INVALID_PIN", "message": "Invalid credentials", ...}`

### 5. Unknown phone → USER_NOT_FOUND

Phone does not match any user or partner:

```bash
curl -s -X POST "http://localhost:8069/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"00000000","pin":"123456"}'
```

- Expected: `401`, `{"success": false, "code": "USER_NOT_FOUND", "message": "User not found", ...}`

---

## Restart and module upgrade

On this server Odoo 19 runs as the **odoo19** systemd service and uses a venv. Use:

```bash
# Restart Odoo 19
sudo systemctl restart odoo19

# Upgrade addon (run once after applying patch; stops after init)
/opt/odoo/venv/bin/python /opt/odoo/odoo19/odoo-bin -c /etc/odoo19.conf -u inguumel_order_mxm --stop-after-init
# Then start Odoo again
sudo systemctl start odoo19
```

To upgrade `inguumel_mobile_api` instead, replace `inguumel_order_mxm` with `inguumel_mobile_api` in the `-u` option.

Replace `localhost:8069` with your Odoo base URL.

---

## Auth login: primary_role, roles, capabilities (verification)

Login response now includes **role** (legacy, unchanged), **primary_role**, **roles[]**, **capabilities{}**, **warehouse_ids[]**. App context from header `X-App: driver|cashier` or query `?app=driver|cashier` is used only for **primary_role** selection.

### Driver + Owner with X-App: driver

```bash
curl -s -X POST "http://localhost:8069/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -H "X-App: driver" \
  -d '{"phone":"99123456","pin":"123456"}' | jq '.data.primary_role, .data.capabilities.can_driver_update_delivery_status, .data.role, .data.roles'
```

- Expect: `primary_role` = "driver", `capabilities.can_driver_update_delivery_status` = true, `role` = legacy value, `roles` = array (e.g. ["driver","warehouse_owner"]).

### Cashier with X-App: cashier

```bash
curl -s -X POST "http://localhost:8069/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -H "X-App: cashier" \
  -d '{"phone":"<CASHIER_PHONE>","pin":"<PIN>"}' | jq '.data.primary_role, .data.capabilities.can_cash_confirm'
```

- Expect: `primary_role` = "cashier", `capabilities.can_cash_confirm` = true.

### Legacy clients (no breaking change)

```bash
curl -s -X POST "http://localhost:8069/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"99123456","pin":"123456"}' | jq '.data.role, .data.uid, .data.warehouse_ids'
```

- Expect: `role`, `uid`, `warehouse_ids` present as before; response also includes `primary_role`, `roles`, `capabilities`.

### Driver app login (capability-based)

```bash
curl -s -X POST "http://localhost:8069/api/v1/driver/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"99123456","pin":"123456"}' | jq '.success, .data.primary_role, .data.capabilities.can_driver_update_delivery_status, .data.warehouse_ids'
```

- Expect: success=true; user with driver capability + warehouse_ids is allowed even when legacy `role` is warehouse_owner.
