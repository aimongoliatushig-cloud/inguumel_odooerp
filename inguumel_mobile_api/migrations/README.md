# Migrations

## 1.0.2 – stock.warehouse location (Integer → Many2one) [RECOMMENDED]

When upgrading to **1.0.2** (from 1.0.0, 1.0.1, or an already-installed broken DB with integer columns):

- **Pre-migrate** (`1.0.2/pre-rename_warehouse_location_columns.py`): Detects if `x_aimag_id` or `x_sum_id` exist as INTEGER; renames them to `x_aimag_id_legacy` and `x_sum_id_legacy` so the ORM does not drop data when creating the new Many2one fields. Wrapped in try/except with logging.
- **Post-migrate** (`1.0.2/post-migrate_warehouse_location_data.py`): Copies legacy integer values into the new Many2one columns, **converts 0 → NULL**, drops legacy columns safely, and logs warnings for warehouses missing aimag/sum mapping.

**Upgrade command:** `odoo -u inguumel_mobile_api` (or via UI: Apps → inguumel_mobile_api → Upgrade).

**Install path:** On first install, `pre_init_hook` and `post_init_hook` in `hooks.py` do the same (with 0→NULL and safety checks); no legacy columns exist so they are no-ops.

## 1.0.0 / 1.0.1 – legacy

Same idea; 1.0.2 is the canonical fix with 0→NULL, safety, and logging.
