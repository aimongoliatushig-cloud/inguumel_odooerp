#!/usr/bin/env python3
"""
One-time repair: create missing outgoing pickings for sale orders in state='sale'.
Uses sale_stock _action_launch_stock_rule (no action_confirm).

From Odoo shell:
  odoo-bin shell -d YOUR_DB

Then in shell:
  result = env['sale.order']._mxm_repair_missing_pickings_batch(order_ids=[51, 52])
  print(result)

Expected: {'order_ids_processed': [51, 52], 'created': {51: [picking_id], 52: [picking_id]}, 'errors': {}}
"""

