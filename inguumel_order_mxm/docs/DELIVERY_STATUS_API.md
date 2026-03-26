# Delivery Status Lifecycle – API and UX

## Canonical status codes

- `received` – Захиалга авлаа  
- `preparing` – Бэлтгэж байна  
- `prepared` – Бэлтгэж дууссан  
- `out_for_delivery` – Хүргэлтэд гарсан  
- `delivered` – Хүргэгдсэн  
- `cancelled` – Цуцлагдсан  

Allowed transitions: `received` → `preparing` → `prepared` → `out_for_delivery` → `delivered`; any non-terminal → `cancelled`. No skipping or invalid back transitions.

## API

### GET /api/v1/orders/{order_id}/delivery

Returns delivery status and timeline for the order. **Auth:** Bearer (mobile user). **Access:** order owner only.

**Response (200):** `data` includes:

| Key | Type | Description |
|-----|------|-------------|
| `order_id` | number | Sale order id |
| `current_status` | object | `{ code, label, at }` – canonical delivery status |
| `timeline` | array | Status history entries `{ code, label, at, is_current, note?, source? }` |
| `last_update_at` | string \| null | ISO datetime of last status change |
| `version` | number | Monotonic version (last log id) for polling |
| `next_actions` | string[] | Allowed next status codes from `MXM_ALLOWED_TRANSITIONS[current_status.code]` (Drive App buttons) |
| `blocked_reason` | null \| "NO_DELIVERY_PICKING" | Set only when `next_actions` is empty (after computing from transitions), current status is not terminal (`delivered`/`cancelled`), and order has no outgoing picking |
| `picking_id` | number \| null | Id of first outgoing picking (from `_mxm_get_outgoing_pickings`) |
| `picking_state` | string \| null | State of first outgoing picking |

**Kill-switch (503):** When disabled: `{ "success": false, "code": "DISABLED", "message": "delivery api disabled by config", "request_id": "...", "data": null, "meta": null }`.

### POST /api/v1/orders/{order_id}/delivery/status

Sets delivery status (validates transition). **Auth:** Bearer. **Access:** staff (`stock.group_stock_user`) or admin (`base.group_system`) only.

**Body:** `{ "status": "prepared", "note": "optional" }`

**Response (200):** Same `data` shape as GET: `order_id`, `current_status`, `timeline`, `last_update_at`, `version`, `next_actions`, `blocked_reason`, `picking_id`, `picking_state`; plus `stock_effect` and `new_status` on success. Driver endpoint `POST /api/v1/driver/orders/<id>/delivery/status` returns the same payload so the app can refresh without refetch.

**Errors:** 400 VALIDATION_ERROR (invalid transition or status), 403 FORBIDDEN (not staff/admin), 503 with **code DISABLED** if kill-switch enabled.

**Kill-switch:** `ir.config_parameter` key `api_disabled:/api/v1/orders/delivery` = `"1"` or `"true"` → both GET and POST return 503 with `code: "DISABLED"`, `data: null`.

## curl examples

```bash
BASE="http://127.0.0.1:8069"

# 1) Login (get token)
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"95909912","pin":"050206"}')
TOKEN=$(echo "$RES" | jq -r '.data.access_token')

# 2) GET delivery (mobile: order owner)
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/orders/5/delivery" | jq .

# 3) POST status (staff/admin)
curl -s -X POST "$BASE/api/v1/orders/5/delivery/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"prepared","note":"Packed"}' | jq .
```

## Verification: next_actions and picking (Drive App)

After patch, GET delivery (both `/api/v1/orders/<id>/delivery` and `/api/v1/driver/orders/<id>/delivery`) returns `next_actions`, `blocked_reason`, `picking_id`, `picking_state`. Use same transition rules as POST (no new business logic).

**Driver login then GET delivery:**
```bash
BASE="http://127.0.0.1:8069"
# Driver login (phone/pin of driver user with warehouse)
RES=$(curl -s -X POST "$BASE/api/v1/auth/login" -H "Content-Type: application/json" -H "X-App: driver" \
  -d '{"phone":"<DRIVER_PHONE>","pin":"<PIN>"}')
TOKEN=$(echo "$RES" | jq -r '.data.access_token')
# GET driver delivery for an order in scope
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/driver/orders/<ORDER_ID>/delivery" \
  | jq '.data.current_status.code, .data.next_actions, .data.picking_id, .data.blocked_reason'
```

**Expected:** `current_status.code` (e.g. `"received"`), `next_actions` (e.g. `["preparing","cancelled"]`), `picking_id` (number or null), `blocked_reason` (null or `"NO_DELIVERY_PICKING"`). For status `received` → `next_actions` = `["preparing","cancelled"]`; for `preparing` → `["prepared","cancelled"]`; for `delivered` → `next_actions` = `[]`.

### Example JSON (preparing)

```json
{
  "success": true,
  "data": {
    "order_id": 42,
    "current_status": { "code": "preparing", "label": "Бэлтгэж байна", "at": "2025-02-09T10:00:00" },
    "timeline": [
      { "code": "received", "label": "Захиалга авлаа", "at": "2025-02-09T09:00:00", "is_current": false, "note": null },
      { "code": "preparing", "label": "Бэлтгэж байна", "at": "2025-02-09T10:00:00", "is_current": true, "note": null }
    ],
    "last_update_at": "2025-02-09T10:00:00",
    "version": 123,
    "next_actions": ["prepared", "cancelled"],
    "blocked_reason": null,
    "picking_id": 56,
    "picking_state": "assigned"
  }
}
```

### Example JSON (out_for_delivery)

```json
{
  "success": true,
  "data": {
    "order_id": 42,
    "current_status": { "code": "out_for_delivery", "label": "Хүргэлтэд гарсан", "at": "2025-02-09T11:00:00" },
    "timeline": [ "... entries ..." ],
    "last_update_at": "2025-02-09T11:00:00",
    "version": 125,
    "next_actions": ["delivered", "cancelled"],
    "blocked_reason": null,
    "picking_id": 56,
    "picking_state": "assigned"
  }
}
```

**Customer GET (order owner):**
```bash
# Use customer token
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/orders/<ORDER_ID>/delivery" \
  | jq '.data.next_actions, .data.picking_id'
```

## Manual test in Odoo UI

1. **Inventory** → **Operations** → **Delivery** (or **Transfers**).
2. Open an **outgoing** transfer linked to a sale order (e.g. SO001).
3. Confirm the card **"ЗАХИАЛГЫН ЯВЦ"** shows and the timeline (received → …).
4. As a **stock user**, click **"Бэлтгэж байна"** → status becomes preparing; timeline updates.
5. Click **"Бэлтгэж дууссан"** → prepared.
6. Click **"Хүргэлтэд гарсан"** → out_for_delivery.
7. Click **"Хүргэгдсэн"** → delivered. **UI note:** The button does **not** auto-validate the picking (inventory integrity decoupled); validate the transfer separately if needed.
8. List view: filter by **"Захиалгын шат"** (e.g. Бэлтгэж байна).

## Migration (existing DBs)

One-time migration uses `ir.config_parameter` key **`mxm.delivery.legacy_migrated`**. If already `true`, no-op. If false, migrates in batches (500 records) then sets to `true`. Run from Odoo shell:

```python
env['mxm.order.status.log']._migrate_legacy_codes()
```
