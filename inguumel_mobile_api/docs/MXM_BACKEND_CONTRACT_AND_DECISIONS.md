# MXM Backend Contract + Шийдвэрүүд (RN талд ашиглах)

---

## ⚠️ Blind spot 1: Curl 127.0.0.1 дээр хийсэн нь RN-ийн асуудлыг батлахгүй

**MUST:** A2–A4 curl тестүүдийг **RN ашиглаж буй яг тэр BASE (public host)** дээр 100% давтаж баталгаажуулна.

- RN нь public host (жишээ нь `http://72.62.247.95:8069`) дээрээс дуудна.
- Curl-ийг зөвхөн `127.0.0.1` дээр хийвэл cookie domain нь `127.0.0.1` болж хадгалагдана.
- RN өөр host руу дуудахад cookie явдаггүй → яг тэгээд "Unauthorized" гардаг.
- **Иймээс "backend OK" гэж дүгнэх боломжгүй** – curl-ийг public BASE дээр ажиллуулах хүртэл.

**Баталгаажуулах:** Server дээр `BASE="http://72.62.247.95:8069"` (эсвэл RN-ийн бодит BASE) тохируулаад `curl_mxm_auth_test.sh` ажиллуулна. Зөвхөн энэ BASE дээр A2–A4 бүгд 200 (categories upgrade дараа 200) бол backend RN-д зориулж OK гэж тооцно.

---

## 1) A2–A4 curl дүгнэлт (127.0.0.1 дээрх жишээ – RN-д хамаарахгүй)

### Ажилласан curl (BASE=http://127.0.0.1:8069 – **RN-ийн асуудлыг батлахгүй**)

| Алхам | Endpoint | HTTP статус | Дүгнэлт |
|-------|----------|-------------|---------|
| A2 Login | POST /api/v1/auth/login | **200** | OK |
| A2 Set-Cookie | Response header | **Set-Cookie: session_id=... байна** | Odoo session_id cookie тохирлоо |
| A3 auth/me | GET /api/v1/auth/me (cookie-оор) | **200** | Session хүлээн ажиллаж байна |
| A3 categories | GET /api/v1/mxm/categories (cookie-оор) | **404** | Route бүртгэгдээгүй – модуль load/upgrade шалгах |
| A3 products | GET /api/v1/mxm/products?warehouse_id=2&limit=5 | **200** | OK |
| A4 cart GET | GET /api/v1/mxm/cart?warehouse_id=2 | **200** | OK |
| A4 cart/lines POST | POST /api/v1/mxm/cart/lines | **400** INSUFFICIENT_STOCK | Auth OK |

**Товч:** 127.0.0.1 дээрх энэ дүгнэлт нь **RN дээрх Unauthorized / categories 404-ийг шийддэггүй**. **Public BASE дээр** A2–A4 давтан ажиллуулж баталгаажуулна.

---

## 2) RN дээр "Unauthorized" – үндсэн шалтгаан

**Backend тал:** curl-ээр cookie-оор auth/me, cart 200 буцаж байгаа тул **session cookie тохирч, backend зөв хүлээн ажиллаж байна.**

**RN дээр Unauthorized гарах боломжит шалтгаанууд:**

1. **Cookie domain mismatch**  
   RN app нь **өөр host** (жишээ нь `http://72.62.247.95:8069`) дээр дуудаж байгаа бол, curl-ийг **яг тэр BASE** дээр ажиллуулна. Хэрэв curl-ийг `127.0.0.1` дээр хийсэн бол cookie-ийн domain нь `127.0.0.1` болно; RN нь бодит host руу request явуулдаг бол **cookie явуулахгүй** (domain таарахгүй).

2. **RN cookie явуулахгүй**  
   Fetch/axios-д `credentials: 'include'` (эсвэл `withCredentials: true`) тохируулаагүй бол cross-origin request-д cookie явахгүй.

3. **Backend session issue**  
   Curl-ээр 200 байгаа тул одоогийн байдлаар backend session асуудалгүй.

**Яг шалгах:** Server дээр RN-ийн **яг ашиглаж буй BASE** (жишээ нь `http://72.62.247.95:8069`)-ийг ашиглан дараахыг ажиллуулна:

```bash
export BASE="http://<RN_BASE_HOST>:8069"
# Дараа нь curl_mxm_auth_test.sh ажиллуулна
```

Хэрэв энэ BASE дээр auth/me, cart 200 бол backend OK; RN талд **credentials: 'include'** болон **request-үүдийг нэг BASE руу явуулах** эсэхийг шалгана.

---

## 3) Cookie хадгалах уу, token руу шилжих үү

**Санал: одоогоор cookie-г үргэлжлүүлэх; шаардлагатай бол дараа нь token.**

**Шалтгаан:**

- Backend аль хэдийн session cookie-ээр зөв ажиллаж байна (curl 200).
- Odoo-гийн session (session_id cookie) нь стандарт, алдаа гарвал debug хялбар.
- Token (Bearer) нь: login response-д token нэмэх, бүх MXM endpoint-д token шалгах middleware/helper нэмэх, RN дээр cookie-ийг орхиод Authorization header явуулах гэх мэт өөрчлөлт ихтэй.

**Хэрэв RN-ээс cookie огт явахгүй (domain/cross-origin-ий улмаас) бол:**

- **Option A (Token):**  
  - POST /api/v1/auth/login → response-д `access_token` (жишээ нь JWT эсвэл session sid) буцаах.  
  - RN → `Authorization: Bearer <token>`.  
  - Backend → MXM endpoint-уудад token verify (session-тай холбох эсвэл token-оор user олох) helper нэмэх.  
  Энэ нь mobile-д domain-оос хамааралгүй, илүү найдвартай.

**Одоогийн шийдвэр:** Cookie-г үргэлжлүүлж, RN талд **BASE нэг байх**, **credentials: 'include'** байгаа эсэхийг баталгаажуулна. Хэрэв бодит base дээр ч cookie явахгүй бол Option A (token) руу шилжих техникийн санал бэлэн.

---

## 3.1) Bearer token (implemented)

- **POST /api/v1/auth/login** response includes `data.access_token` (non-empty string). Use it for Bearer auth.
- **GET /api/v1/auth/me** and **GET /api/v1/mxm/orders** (and other /api/v1 routes) accept `Authorization: Bearer <access_token>`; `ir.http._pre_dispatch` sets `session.uid` from the token.

**Curl – login and use Bearer for auth/me and orders:**

```bash
BASE="http://127.0.0.1:8069"

# 1) Login – get access_token
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"95909912","pin":"050206"}')
echo "$RES" | jq .
TOKEN=$(echo "$RES" | jq -r '.data.access_token // empty')
# 2) auth/me with Bearer
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/auth/me" | jq .
# 3) mxm/orders with Bearer
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/mxm/orders" | jq .
```

---

## 4) Categories endpoint баталгаажуулалт

### ⚠️ Blind spot 2: Categories 404 – route бүртгэгдээгүй; "module load" асуудал ч байж болно

Categories.py байгаа мөртлөө 404 гэдэг нь дараах аль нэгээс болсон байж болно:

- модуль upgrade хийгдээгүй, эсвэл
- **controllers __init__.py дээр import хийгдээгүй / ачаалагдаагүй**, эсвэл
- **addons path эсвэл load order алдаа** (модуль бүр Odoo-д ачаалагдаагүй)

**Upgrade хийхээс өмнө шалгах (MUST):**

1. **Database дээр module state**
   - `ir_module_module` дээр `inguumel_catalog_mxm`-ийн `state = 'installed'` эсэхийг шалга.
   - SQL: `SELECT name, state FROM ir_module_module WHERE name = 'inguumel_catalog_mxm';`
   - Эсвэл Odoo Apps (Developer mode) → "Inguumel Catalog MXM" → installed эсэх.

2. **Odoo log дээр controllers load**
   - Odoo-г restart хийсний дараа log-оос `inguumel_catalog_mxm` эсвэл `/api/v1/mxm/categories` холбоотой мөр гарч байгаа эсэх (route бүртгэгдсэн эсэх).

3. **controllers/__init__.py**
   - `inguumel_catalog_mxm/controllers/__init__.py` дотор `from . import categories` байгаа эсэх (одоо байгаа).

### ⚠️ Blind spot 3: Upgrade команд – "Unknown command 'server'" гэж гарч байсан тул зөв командаар стандартчилна

Зарим Odoo 19 суулгалтад `odoo-bin server -c ...` гэхэд "Unknown command 'server'" гардаг. Тиймээс plan дээр **ажилладаг нэг стандарт команд** ашиглана.

**Стандарт upgrade (DB нэр заавал):**

```bash
# Конфигоос DB нэрийг унших: grep db_name /etc/odoo19.conf
# Дараа нь (odoo хэрэглэгчээр эсвэл systemd-ийн ExecStart-тай ижил хэрэглэгчээр):
odoo-bin -c /etc/odoo19.conf -d <DB_NAME> -u inguumel_catalog_mxm --stop-after-init
# Жишээ: -d odoo эсвэл -d production
```

**Дараа нь Odoo service дахин асаана:**

```bash
sudo systemctl restart odoo19
```

**Хэрэв "Unknown command" гэж гарвал:** `odoo-bin --help` ажиллуулаад тухайн Odoo-д ямар subcommand байгааг шалгана. Зарим суулгалтад `odoo-bin server -c ... -d ... -u ...` хэрэгтэй байж болно – тухайн серверийн `ExecStart` (systemctl cat odoo19)-аас яг командыг авна.

**Дараа нь баталгаажуулах (MUST – RN-ийн public BASE ашиглана):**

```bash
# 1) Login, cookie хадгалах
curl -i -c /tmp/mxm_cookies.txt -H "Content-Type: application/json" \
  -d '{"phone":"95909912","pin":"050206"}' "$BASE/api/v1/auth/login"

# 2) Categories
curl -s -b /tmp/mxm_cookies.txt "$BASE/api/v1/mxm/categories" | jq .
```

**Хүлээгдэх response shape:**

```json
{
  "success": true,
  "code": "OK",
  "message": "OK",
  "request_id": "<uuid>",
  "data": [
    { "id": 1, "name": "All", "parent_id": null, "sequence": 1, "image_url": null },
    { "id": 2, "name": "Food", "parent_id": 1, "sequence": 1, "image_url": null }
  ],
  "meta": { "count": 2 }
}
```

Categories нь **session шаарддаг** (401 без cookie). RN: нэвтрэх → cookie хадгалах → GET /api/v1/mxm/categories-д **credentials: 'include'** ашиглана.

---

## 5) Excel import – "Барааны ангилал" match дүрэм

### Odoo ямар утгаар match хийдэг вэ

- **product.template**-ийн **categ_id** нь Many2one → **product.category**.
- **product.category**-ийн **_rec_name** = **complete_name** (Odoo 19).
- Import-д Many2one талбар нь **display value**-аар match хийдэг, өөрөөр хэлбэл **complete_name**-ээр.

**complete_name форматын дүрэм (Odoo код):**

- `complete_name = '%s / %s' % (parent_id.complete_name, name)` → **зай + "/" + зай** (жишээ нь `"Food / Meat"`).
- Excel-д **"Food/Meat"** (зайгүй) гэж бичвэл match хийгдэхгүй; **"Food / Meat"** гэж яг ийм форматаар бичнэ.

### Яг утгуудыг авах (манай DB дээр)

**Backend:** GET /api/v1/mxm/category-names нь **реализлагдсан** – `inguumel_catalog_mxm/controllers/categories.py` дотор `category_names()` method. Session шаарддаг; RN болон Excel хоёуланд ашиглаж болно.

**Сонголт A – API (recommended):**  
Upgrade/load дараа session-тай дуудаж болно:

```bash
curl -s -b /tmp/mxm_cookies.txt "$BASE/api/v1/mxm/category-names" | jq .
```

Response: `data: [{ "id", "name", "complete_name" }, ...]`. Excel-ийн "Барааны ангилал" баганад **complete_name** утгыг яг хуулж тавьна.

**Сонголт B – Odoo shell:**

```python
env['product.category'].search([]).mapped('complete_name')
# эсвэл
[(c.id, c.name, c.complete_name) for c in env['product.category'].search([], order='complete_name')]
```

**Сонголт C – SQL:**

```sql
SELECT id, name, complete_name FROM product_category ORDER BY complete_name;
```

### Excel дээр ямар value бичих вэ (final rule)

- **A) complete_name string:**  
  "Барааны ангилал" баганад дээрх API/shell/SQL-аас авсан **complete_name**-ийг **яг ижил бичнэ** (зай, том/жижиг үсэг, тэмдэгт). Жишээ: `Food / Meat`, `Beverages / Alcohol`.

- **B) External ID:**  
  Import mapping-д **categ_id/id** (эсвэл Odoo-гийн "External ID" багана) ашиглаж, утга нь жишээ нь `__import__.product_category_2` эсвэл өөрийн XML id байна. Ингэвэл string match алдаа гарахгүй.

**Deliverable:** Excel-д "Барааны ангилал"-д **API-аас авсан complete_name-үүдийг яг хуулж тавих**, эсвэл **categ_id/id-оор External ID ашиглах**.

---

## Backend contract (RN талд ашиглах)

| Төлөв | Утга |
|-------|------|
| Auth | Session cookie (session_id). Login → Set-Cookie; дараагийн request-д Cookie header явуулна. |
| 401 | `{ "success": false, "code": "UNAUTHORIZED", "message": "Unauthorized", "request_id": "..." }` |
| Categories | GET /api/v1/mxm/categories (session required). Optional ?warehouse_id= |
| Category names (Excel/RN) | GET /api/v1/mxm/category-names (session required) → data: [{ id, name, complete_name }]. **Реализлагдсан:** `inguumel_catalog_mxm/controllers/categories.py` – category_names(). |
| Products | GET /api/v1/mxm/products?warehouse_id=...&category_id=...&page=1&limit=20. Product item: category_id, category_name, category_path орно (upgrade дараа). |
| Cart | GET/POST/PATCH/DELETE /api/v1/mxm/cart, /api/v1/mxm/cart/lines (session required). |

**RN-д:** Бүх MXM API дуудалт **RN-ийн яг ашиглаж буй public BASE** руу, **credentials: 'include'** ашиглана. Curl-ийг ч гэсэн **тэр BASE** дээр ажиллуулж "backend OK" гэдгийг баталгаажуулна. Хэрэв RN BASE өөр domain бол cookie явахгүй → Unauthorized; тэр тохиолдолд token (Option A) руу шилжих санал бэлэн.
