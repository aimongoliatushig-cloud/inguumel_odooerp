# Drive App API – Driver auth + warehouse-scoped orders

Base URLs: Production `http://72.62.247.95:8069` | Local `http://localhost:8069`

All responses include: `success`, `code`, `message`, `request_id`. Use `request_id` in logs to trace production 500s.

---

## 1. Driver login

**POST** `/api/v1/driver/auth/login`  
Body: `{ "login": "<string>", "password": "<string>" }`

- Authenticates against `res.users` (standard Odoo).
- Only allows users with **non-empty `x_warehouse_ids`** (403 `WAREHOUSE_NOT_ASSIGNED` if empty).
- Returns 200 with `uid`, `partner_id`, `access_token`, `expires_in`, `role`, `warehouse_ids`.

```bash
# 1) Driver login (replace with real login/password for a user with x_warehouse_ids)
BASE="http://localhost:8069"
RES=$(curl -s -w "\nHTTP_CODE:%{http_code}" -X POST "$BASE/api/v1/driver/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"login":"driver1","password":"123123"}')
HTTP_CODE=$(echo "$RES" | tail -n1)
BODY=$(echo "$RES" | sed '$d')
echo "HTTP $HTTP_CODE"
echo "$BODY" | jq .
TOKEN=$(echo "$BODY" | jq -r '.data.access_token // empty')
```

---

## 2. Driver auth/me

**GET** `/api/v1/driver/auth/me`  
Header: `Authorization: Bearer <access_token>`

Returns `uid`, `partner_id`, `role`, `warehouse_ids`. 401 if not authenticated; 403 `FORBIDDEN` or `WAREHOUSE_NOT_ASSIGNED` if not a valid driver.

```bash
# 2) Driver me (use TOKEN from step 1)
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/auth/me" | jq .
```

---

## 3. Driver orders list

**GET** `/api/v1/driver/orders?limit=50&offset=0`  
Header: `Authorization: Bearer <access_token>`

- 403 `FORBIDDEN` if not warehouse owner.
- 403 `WAREHOUSE_NOT_ASSIGNED` if `warehouse_ids` empty.
- Otherwise returns orders filtered by `warehouse_id IN user.x_warehouse_ids`.

```bash
# 3) Orders list (limit max 50)
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/orders?limit=50&offset=0" | jq .
ORDER_ID=$(curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/orders?limit=1" | jq -r '.data[0].order_id // empty')
```

---

## 4. Driver order detail

**GET** `/api/v1/driver/orders/<order_id>`  
Header: `Authorization: Bearer <access_token>`

403 if order belongs to another warehouse.

```bash
# 4) Order detail (use ORDER_ID from list or a known id)
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/orders/$ORDER_ID" | jq .
```

---

## 5. Driver delivery (GET)

**GET** `/api/v1/driver/orders/<order_id>/delivery`  
Header: `Authorization: Bearer <access_token>`

```bash
# 5) Get delivery status + timeline
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/orders/$ORDER_ID/delivery" | jq .
```

---

## 6. Driver delivery status update (POST)

**POST** `/api/v1/driver/orders/<order_id>/delivery/status`  
Header: `Authorization: Bearer <access_token>`  
Body: `{ "status": "received|preparing|prepared|out_for_delivery|delivered|cancelled", "note": "optional" }`

Allowed transitions enforced by backend.

```bash
# 6) Set delivery status
curl -s -X POST "$BASE/api/v1/driver/orders/$ORDER_ID/delivery/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"preparing","note":"Driver app"}' | jq .
```

---

## Kill-switch

`ir.config_parameter`: `api_disabled:/api/v1/driver` = `"1"` or `"true"` → all driver endpoints return 503, `code: "DISABLED"`.

---

## Test checklist (403 rules)

1. **Missing group / not warehouse owner**
   - Create a `res.users` with login/password but **do not** assign any warehouse (`x_warehouse_ids` empty).
   - **POST** `/api/v1/driver/auth/login` with that user’s login/password.
   - **Expected:** 403, `code: "WAREHOUSE_NOT_ASSIGNED"`, message e.g. "No warehouse assigned".

2. **Empty x_warehouse_ids**
   - User is in "Warehouse Owner" group but `x_warehouse_ids` is empty.
   - **POST** `/api/v1/driver/auth/login`.
   - **Expected:** 403, `code: "WAREHOUSE_NOT_ASSIGNED"` (do **not** return 200 with empty order lists).

3. **Driver auth/me without warehouse**
   - Log in as a normal customer (no warehouses) via `/api/v1/auth/login`, get Bearer token.
   - **GET** `/api/v1/driver/auth/me` with that token.
   - **Expected:** 403 `FORBIDDEN` or `WAREHOUSE_NOT_ASSIGNED` (depending on role/field).

4. **Driver orders with customer token**
   - Same customer token as above.
   - **GET** `/api/v1/driver/orders`.
   - **Expected:** 403 (not 200 with empty list).

5. **Order from other warehouse**
   - Log in as driver A (warehouses [1]). Get order_id of an order in warehouse 2.
   - **GET** `/api/v1/driver/orders/<order_id>` with driver A’s token.
   - **Expected:** 403 `FORBIDDEN`.

6. **Logging**
   - Trigger a 500 (e.g. misconfigured DB) and check logs: every log line for that request must include `request_id` so production 500s can be traced.

---

## Odoo ERP setup (driver users)

1. **Security group:** "Warehouse Owner" is created by module `inguumel_order_mxm` (category: Inguumel Order).
2. **Create driver user:** Settings → Users → Create (or edit):
   - **Login:** unique (e.g. phone number).
   - **Password:** set (e.g. 123123).
   - **Other:** Add to group **Warehouse Owner**.
   - **Mobile / Warehouse Owner** tab: Assign at least one warehouse to **Assigned Warehouses (Warehouse Owner)** (`x_warehouse_ids`).
3. Without at least one warehouse, driver login returns 403 `WAREHOUSE_NOT_ASSIGNED`.
