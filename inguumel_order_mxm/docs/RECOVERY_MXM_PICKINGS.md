# Recovery: Missing MXM Outgoing Pickings (S00014+)

For confirmed MXM orders that have no outgoing `stock.picking` (e.g. S00014+ with `origin` "MXM Mobile" / "MXM Cart" but no picking), use the model method `_mxm_recover_missing_pickings`.

## From Odoo shell

```bash
sudo -u odoo /opt/odoo/venv/bin/python /opt/odoo/odoo19/odoo-bin shell -c /etc/odoo19.conf -d InguumelStage
```

Then:

```python
# Dry run: list orders that would get a picking
result = env['sale.order']._mxm_recover_missing_pickings(dry_run=True)
print(result)  # {'dry_run': True, 'order_count': N, 'order_names': [...], 'order_ids': [...]}

# Execute: create missing pickings (and set x_order_source on legacy orders)
result = env['sale.order']._mxm_recover_missing_pickings(dry_run=False)
print(result)  # {'dry_run': False, 'created': [(order_name, picking_id), ...]}
```

## Scope

- Orders with `state='sale'` and `x_order_source in ('mxm_mobile', 'mxm_cart')` **or** `origin` containing `'MXM'` (and no `x_order_source` set).
- Only orders that have **no** outgoing picking (by `_mxm_get_outgoing_pickings()`).
- Legacy orders (origin "MXM Mobile" / "MXM Cart" without `x_order_source`) get `x_order_source` set before creating the picking.

## Optional: limit to specific orders

```python
result = env['sale.order']._mxm_recover_missing_pickings(dry_run=False, order_ids=[14, 15, 16])
```
