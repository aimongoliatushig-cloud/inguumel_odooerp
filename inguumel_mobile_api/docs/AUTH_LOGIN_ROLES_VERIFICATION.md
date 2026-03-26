# Auth login: primary_role, roles, capabilities – verification

## Summary

POST `/api/v1/auth/login` and driver login now return a stable authorization contract while keeping legacy `role` unchanged:

- **`role`** – legacy single string (unchanged; backward compatible).
- **`primary_role`** – string chosen with optional app context (X-App or `?app=`).
- **`roles`** – array of all roles from group membership.
- **`capabilities`** – object with booleans: `can_driver_update_delivery_status`, `can_cash_confirm`, `can_manage_warehouse`.
- **`warehouse_ids`** – list of warehouse IDs (unchanged).

App context is read from header `X-App: driver` or `X-App: cashier`, or query `?app=driver` / `?app=cashier`. It is used only to select `primary_role`, not for permission granting.

Driver API allows login when the user has **driver capability** and non-empty **warehouse_ids**, regardless of legacy `role` (e.g. warehouse_owner).

---

## Curl verification

Replace `BASE`, `PHONE`, `PIN` with your instance URL, phone, and PIN.

### 1) Driver + Warehouse Owner login with X-App: driver

Expect: `primary_role=driver`, `capabilities.can_driver_update_delivery_status=true`, legacy `role` may be `warehouse_owner` or `driver`.

```bash
curl -s -X POST "${BASE}/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -H "X-App: driver" \
  -d "{\"phone\":\"${PHONE}\",\"pin\":\"${PIN}\"}" | jq .
```

Check:

- `jq '.data.primary_role'` → `"driver"`
- `jq '.data.capabilities.can_driver_update_delivery_status'` → `true`
- `jq '.data.roles'` → array containing `"driver"` and possibly `"warehouse_owner"`
- `jq '.data.role'` → legacy value (unchanged)

### 2) Same with query param

```bash
curl -s -X POST "${BASE}/api/v1/auth/login?app=driver" \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"${PHONE}\",\"pin\":\"${PIN}\"}" | jq '.data.primary_role, .data.capabilities'
```

Expect `primary_role` = `"driver"` when user has driver capability.

### 3) Cashier login

Expect: `primary_role=cashier`, `capabilities.can_cash_confirm=true`.

```bash
curl -s -X POST "${BASE}/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -H "X-App: cashier" \
  -d "{\"phone\":\"${CASHIER_PHONE}\",\"pin\":\"${CASHIER_PIN}\"}" | jq '.data.primary_role, .data.capabilities.can_cash_confirm'
```

### 4) Legacy clients (no breaking changes)

Clients that only read `.data.role` must still work:

```bash
curl -s -X POST "${BASE}/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"${PHONE}\",\"pin\":\"${PIN}\"}" | jq '.data.role, .data.uid, .data.warehouse_ids'
```

Expect: `role` present and unchanged; `uid`, `warehouse_ids` as before; response also includes `primary_role`, `roles`, `capabilities`.

### 5) Driver app login (phone+pin) – capability-based

User with driver capability + warehouse_ids should get 200 and full payload including capabilities:

```bash
curl -s -X POST "${BASE}/api/v1/driver/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"phone\":\"${PHONE}\",\"pin\":\"${PIN}\"}" | jq '.success, .data.primary_role, .data.capabilities.can_driver_update_delivery_status, .data.warehouse_ids'
```

Expect: `success=true`, `primary_role=driver` (when app context is driver), `can_driver_update_delivery_status=true`, `warehouse_ids` non-empty. User is **not** rejected because legacy `role` is `warehouse_owner`.

---

## Restart / upgrade

After deploying:

```bash
# Restart Odoo (adjust service name as needed)
sudo systemctl restart odoo

# Or upgrade modules
odoo-bin -c odoo.conf -u inguumel_mobile_api,inguumel_order_mxm --stop-after-init
```
