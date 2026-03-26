# Bearer Auth Fix – Deliverables

## 1. Root cause (why auth/me worked but mxm/* failed)

- **auth/me** reads **`request.session.uid`** only. Our code set `session.uid` in `_pre_dispatch` (after `super()`), so auth/me saw the token user and returned 200.
- **mxm/*** (e.g. cart) uses **`request.env.user`** in `_require_user()`. That comes from the env set during **`_authenticate`**:
  - Base runs `_authenticate_explicit('public')` → **`check_session(session)`** when **`session.uid` is not None**.
  - If we set `session.uid` in **`_authenticate`**, Bearer-only requests have a **new session (no cookie)** so **`session.session_token`** is missing → **`check_session()` fails** → base does **`request.env = Environment(cr, None, context)`** and then **`_auth_method_public`** sets public user → **mxm/* sees public user → 401**.
- So: setting **session.uid in _authenticate** caused check_session to run and reset env to public for Bearer-only requests. **auth/me** still worked because it only checks **session.uid** (set later in _pre_dispatch). **mxm/*** failed because **request.env.user** was already forced to public in _authenticate.

**500 on auth/me:** In Odoo 19, **`request.uid`** is deprecated; its **setter raises `NotImplementedError("Use request.update_env instead.")`**. Any `request.uid = uid` in our code caused a 500. Fix: **do not set request.uid**; use only **`request.update_env(user=uid)`**.

---

## 2. Correct backend logic (ir_http.py)

- **`_authenticate`:** For `/api/v1` + `Authorization: Bearer <token>`:
  - Resolve token → uid via **`api.access.token`**.
  - If valid: **only** **`request.update_env(user=uid)`**. Do **not** set **session.uid** here (so **check_session()** is never run and env is not reset to public).
- **`_pre_dispatch`:** For `/api/v1` + Bearer:
  - Resolve token → **resolved_uid**; set **`request.update_env(user=uid)`** (so controller sees token user even if base did something to env).
  - Call **`super()._pre_dispatch(rule, args)`**.
  - **Only after super():** set **`request.session.uid = resolved_uid`**, **`request.update_env(user=resolved_uid)`**, and **session.login**.
- **Do not** set **`request.uid`** anywhere (Odoo 19 setter raises).
- All logic guarded in **try/except** so no 500 from our code; DEBUG log wrapped so it never raises.

---

## 3. curl proof (expected)

After **`sudo systemctl restart odoo19.service`**:

```bash
BASE="http://127.0.0.1:8069"  # or your host
# 1) Login
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" -d '{"phone":"95909912","pin":"050206"}')
TOKEN=$(echo "$RES" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('data',{}).get('access_token','') or '')")

# 2) auth/me → 200
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/auth/me"
# Expected: 200

# 3) mxm/cart → 200
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/cart?warehouse_id=1"
# Expected: 200

# 4) mxm/categories → 200
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/categories"
# Expected: 200

# 5) Invalid token → 401 (JSON)
curl -s -H "Authorization: Bearer invalid" "$BASE/api/v1/auth/me" | head -1
# Expected: {"success": false, "code": "UNAUTHORIZED", ...}
```

Or run the script:

```bash
cd /opt/odoo/custom_addons/inguumel_mobile_api
BASE="http://127.0.0.1:8069" bash scripts/verify_bearer_auth.sh
```

Expected: all steps OK, no FAIL.

---

## 4. RN client.ts + authStore.ts patches (templates)

Mobile app was not in this repo; apply these patterns in your React Native/Expo project.

### 4.1 Single source of truth: memoryToken

- **Module-level:** `let memoryToken: string | null = null`.
- **AsyncStorage** used only in **hydrate()** (e.g. on app start) to load token into **memoryToken**.
- **Axios interceptor** reads **memoryToken** synchronously; no AsyncStorage access per request.

### 4.2 client.ts (axios)

- One shared axios instance for all /api/v1/* (including mxm/*).
- Request interceptor: set **`Authorization: Bearer ${memoryToken}`** when **memoryToken** is set.
- Response interceptor: on **401**, call a single **onUnauthorized()** (e.g. from authStore) that:
  - Deduplicates (e.g. one alert / 30s).
  - Cancels in-flight requests (e.g. AbortController or axios cancel token).
  - Clears **memoryToken** and auth state; does **not** retry in a loop.
- Cancelled requests: handle **isCancel** / **AxiosError** with **code === 'ERR_CANCELED'** and do **not** show UI error.

### 4.3 authStore.ts (login sequencing)

- After login success:
  1. **await setAccessToken(token)** (writes to AsyncStorage for next hydrate).
  2. **memoryToken = token**.
  3. **authStatus = LOGGED_IN** (or equivalent).
  4. **Only then** trigger initial fetches (categories, products, cart).
- Guards: any auto-fetch (e.g. on focus or mount) must check **authStatus === LOGGED_IN** (or equivalent); if not, do nothing (no request).

### 4.4 UX (Orders screen)

- If user is logged out: show **«Нэвтрэх»** CTA; do **not** show **«Алдаа гарлаа»** for 401.
- Show real network/connection errors only when appropriate.

---

## 5. Verification checklist

### Backend

- [ ] **Restart:** `sudo systemctl restart odoo19.service`
- [ ] **Login:** `POST /api/v1/auth/login` → 200, body contains `data.access_token`
- [ ] **auth/me:** `GET /api/v1/auth/me` with `Authorization: Bearer <token>` → 200 (no 500)
- [ ] **mxm/cart:** `GET /api/v1/mxm/cart?warehouse_id=1` with same header → 200
- [ ] **mxm/categories:** `GET /api/v1/mxm/categories` with same header → 200
- [ ] **mxm/products:** `GET /api/v1/mxm/products?warehouse_id=1&limit=5` with same header → 200
- [ ] **Invalid token:** `Authorization: Bearer invalid` → 401, JSON body with `code: "UNAUTHORIZED"`
- [ ] Optional: set **DEBUG_MOBILE_AUTH=1** in odoo19.service env; check **/opt/odoo/log/odoo19.log** for one log line per /api/v1/ request (path, auth_present, scheme_bearer, token_masked, resolved_uid, session_uid, env_user_id)

### Mobile

- [ ] **memoryToken** is the single source of truth; AsyncStorage only in hydrate()
- [ ] Axios interceptor uses **memoryToken** only (no AsyncStorage per request)
- [ ] Login sequence: setAccessToken → memoryToken → authStatus → then fetch categories/products/cart
- [ ] All mxm/* use the same axios instance with Bearer header
- [ ] 401: deduplicated logout, cancel in-flight, no retry loop; cancelled requests silent in UI
- [ ] Orders screen: when logged out show «Нэвтрэх», not «Алдаа гарлаа» for 401
