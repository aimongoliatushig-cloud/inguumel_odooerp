# Delivery Status Hardening – Summary

## Files changed + reasons

| File | Changes |
|------|--------|
| **models/stock_picking.py** | "Хүргэгдсэн" button no longer auto-validates picking (inventory integrity decoupled). Added `PICKING_VALIDATE_ON_OUT_FOR_DELIVERY` (default False); if True, validate picking when status set to out_for_delivery. Kept `PICKING_DONE_MEANS_DELIVERED` with comment. `action_mxm_delivered` returns True only (no `button_validate()`). |
| **models/sale_order.py** | Race-condition guard in `_mxm_set_status`: read last log; if same status and (now - last.at) < `MXM_STATUS_DEDUP_SECONDS` (10s), skip creating duplicate log. Transition validation and error message unchanged. |
| **models/mxm_order_status_log.py** | Legacy migration one-time: check `ir.config_parameter` key `mxm.delivery.legacy_migrated`; if true, no-op. If false, migrate in batches (`LEGACY_BATCH_SIZE` 500), then set param to true. Safe for large DB. |
| **controllers/delivery.py** | Kill-switch returns explicit `{ success: false, code: "DISABLED", message: "delivery api disabled by config", data: null }` (503). Added `data.version` (monotonic, last log id) in GET and POST delivery responses for efficient polling. |
| **docs/DELIVERY_STATUS_API.md** | Updated: version, DISABLED response, UI note (button does not validate picking), migration param. |

## Module upgrade command

```bash
odoo-bin -c /path/to/odoo.conf -d InguumelStage -u inguumel_order_mxm --stop-after-init
# Or via UI: Apps → inguumel_order_mxm → Upgrade
```

## 2 curl tests

**1) GET delivery (200, includes version)**

```bash
BASE="http://127.0.0.1:8069"
TOKEN="<your_bearer_token>"
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/orders/5/delivery" | jq '.data.version, .data.current_status'
# Expect: integer version, current_status object
```

**2) POST status (200, same shape with version)**

```bash
curl -s -X POST "$BASE/api/v1/orders/5/delivery/status" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"prepared","note":"Test"}' | jq '.success, .data.version, .data.current_status.code'
# Expect: true, version number, "prepared"
```

**Kill-switch test (503, DISABLED):** Set `api_disabled:/api/v1/orders/delivery` = "true", then same GET → expect `success: false`, `code: "DISABLED"`, `data: null`.

## UI note

- **"Хүргэгдсэн" button** no longer validates the picking. Delivery status and stock moves are decoupled; validate the transfer separately (Validate button or Inventory flow) when appropriate.
- Optional policy `PICKING_VALIDATE_ON_OUT_FOR_DELIVERY` (default False): if set True in code, the "Хүргэлтэд гарсан" button will validate the picking when setting status to out_for_delivery.
