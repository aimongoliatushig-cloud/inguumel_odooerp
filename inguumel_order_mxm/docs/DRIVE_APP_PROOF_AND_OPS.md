# Drive App – Proof & Ops (InguumelStage)

**DB:** InguumelStage · **Service:** `odoo19` · **Config:** `/etc/odoo19.conf`

---

## Why POST /delivery/status can return 403

- **POST** requires **staff**, **admin**, or **warehouse_owner** (`_require_staff_or_admin_or_warehouse_owner`).
- **Warehouse_owner** = `res.users` with **Assigned Warehouses** (`x_warehouse_ids`) set in Odoo (Settings → Users → user → Assigned Warehouses).
- If the token is for a **customer** (no stock group, no system group, no `x_warehouse_ids`), POST correctly returns **403** with message: *"Access denied. This app is only for warehouse and delivery staff."*
- Logs now include: `uid`, `has_stock`, `has_system`, `is_warehouse_owner`, `warehouse_ids`, `request_id` for every 403 from that check.

**Fix for Drive:** Use a **warehouse_owner** user: set **Assigned Warehouses** for that user in Odoo, then log in with that user’s phone+pin and use the returned token for GET/POST delivery.

---

## Curl proof (warehouse_owner token)

Set `BASE` and use a warehouse_owner phone/pin to get `TOKEN`.

```bash
BASE="https://your-host/odoo"   # or http://72.62.247.95:8069
# 1) Login – must return role="warehouse_owner" and warehouse_ids non-empty
curl -s -X POST "$BASE/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"phone":"<WAREHOUSE_STAFF_PHONE>","pin":"<PIN>"}' | jq '{ success, data: { uid: .data.uid, role: .data.role, warehouse_ids: .data.warehouse_ids } }'
# Expect: success true, data.role "warehouse_owner", data.warehouse_ids non-empty array

TOKEN="<access_token from above>"
ORDER_ID=11

# 2) GET delivery – must return received + timeline length >= 1 + version > 0
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/orders/$ORDER_ID/delivery" | jq '{ success, data: { order_id: .data.order_id, current_status: .data.current_status, timeline_count: (.data.timeline | length), version: .data.version } }'
# Expect: success true, current_status.code "received", timeline_count >= 1, version > 0

# 3) POST delivery status – must return success and updated payload (version increments)
curl -s -X POST "$BASE/api/v1/orders/$ORDER_ID/delivery/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"preparing"}' | jq '{ success, data: { current_status: .data.current_status, version: .data.version } }'
# Expect: success true, current_status.code "preparing", version incremented
```

---

## DB proof (after GET then POST)

```sql
-- Order 11 delivery status
SELECT mxm_delivery_status FROM sale_order WHERE id = 11;

-- Last 3 status logs for order 11
SELECT id, code, source FROM mxm_order_status_log WHERE order_id = 11 ORDER BY id DESC LIMIT 3;
```

After a GET that initializes and a POST to "preparing": `mxm_delivery_status` = `'preparing'`; at least two rows in `mxm_order_status_log` (e.g. `received`, `preparing`).

---

## Ops commands

**Important:** PostgreSQL is usually configured with **peer** authentication on the socket. The OS user must match the DB user (`odoo`). So **never run Odoo or odoo-bin as root**; use `sudo -u odoo` so peer auth succeeds.

```bash
# Restart Odoo 19 (service runs as User=odoo, so it's fine)
sudo systemctl restart odoo19

# Logs
journalctl -u odoo19 --no-pager -n 200

# If logfile is set in /etc/odoo19.conf, also:
# tail -f /path/to/odoo19.log

# Upgrade module (MUST run as odoo user – peer auth)
sudo -u odoo /opt/odoo/venv/bin/python /opt/odoo/odoo19/odoo-bin -c /etc/odoo19.conf -d InguumelStage -u inguumel_order_mxm --stop-after-init
sudo systemctl restart odoo19
```

**If you see "Peer authentication failed for user odoo":** you ran the command as root. Use `sudo -u odoo` before the python/odoo-bin command. The service (`systemctl start odoo19`) is already correct because it uses `User=odoo` in the unit.

---

## GET delivery: initial status and cache

- **GET** `/api/v1/orders/<id>/delivery` calls `order.sudo()._mxm_ensure_initial_delivery_status()` so orders with no logs get one `received` log and `mxm_delivery_status = 'received'`.
- After that, the controller calls **`order.invalidate_recordset()`** so the payload is built from the updated data (timeline length ≥ 1, version > 0).
