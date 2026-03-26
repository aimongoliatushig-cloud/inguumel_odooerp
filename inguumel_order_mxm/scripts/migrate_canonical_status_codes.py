# -*- coding: utf-8 -*-
"""
One-time migration: update mxm.order.status.log code from old (RECEIVED, PACKED, etc.)
to canonical lowercase (received, prepared, etc.). Run with: odoo-bin shell -d DB -i inguumel_order_mxm
Then: exec(open('inguumel_order_mxm/scripts/migrate_canonical_status_codes.py').read())
Or run from Odoo shell: env['mxm.order.status.log']._migrate_legacy_codes()
"""
OLD_TO_NEW = {
    "RECEIVED": "received",
    "PREPARING": "preparing",
    "PACKED": "prepared",
    "OUT_FOR_DELIVERY": "out_for_delivery",
    "DELIVERED": "delivered",
    "CANCELLED": "cancelled",
}


def migrate_logs(env):
    Log = env["mxm.order.status.log"].sudo()
    for old, new in OLD_TO_NEW.items():
        count = Log.search_count([("code", "=", old)])
        if count:
            Log.search([("code", "=", old)]).write({"code": new})
            print("Updated %d log(s) from %s -> %s" % (count, old, new))
    # Sync sale.order.mxm_delivery_status from last log for orders that have logs but no delivery_status
    SaleOrder = env["sale.order"].sudo()
    orders = SaleOrder.search([("mxm_delivery_status", "=", False), ("mxm_status_log_ids", "!=", False)])
    for order in orders:
        last = order.mxm_status_log_ids.sorted("at", reverse=True)[:1]
        if last and last.code:
            order.write({"mxm_delivery_status": last.code})
            print("Set order %s mxm_delivery_status = %s" % (order.name, last.code))


# When run as script in shell, env is available
if __name__ != "__main__" and "env" in dir():
    migrate_logs(env)
    print("Migration done.")
