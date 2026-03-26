# COD operational confirmation – migration note

## New fields (sale.order)

- `x_cod_confirmed` (Boolean, default False)
- `x_cod_confirmed_at` (Datetime)
- `x_cod_confirmed_by` (Many2one res.users)
- `x_cod_amount` (Monetary, company currency)
- `x_invoice_status_display` (computed Char, for tree view)

`x_payment_method` already exists in the module; no change to its selection.

## Existing orders

- **x_payment_method:** Already present; existing COD orders keep `x_payment_method = 'cod'`. No migration needed.
- **New COD fields:** Default to False/NULL/0; driver confirm sets them when the endpoint is used.
- **x_invoice_status_display:** Computed from `invoice_status`, `x_payment_method`, `x_cod_confirmed`. No data migration.

## Behaviour

- Creating or confirming COD orders does **not** create `account.move` (invoices). Driver confirm only sets the operational fields and appends a timeline log.
- Sales tree view shows "COD – Хүлээгдэж байна" / "COD – Баталгаажсан" (or "COD - Pending" / "COD - Confirmed") instead of the standard invoice status for COD orders.

## Upgrade

1. Update module: `inguumel_order_mxm`.
2. No shell script required.
3. Optional: ensure drivers use `POST /api/v1/driver/orders/<id>/cod/confirm` for new COD confirmations.
