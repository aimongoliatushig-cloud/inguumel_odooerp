# Delivery Dashboard (Хүргэлт)

## Goal

Delivery operations are separated from Sales and Inventory. All delivery status changes happen in one place: **Inguumel → Хүргэлт** (Delivery Workbench).

## Menu

- **Inguumel** (top-level)
  - **Хүргэлт** → opens the delivery list (sale orders that require delivery)

Visible only to **Inventory / User** (`stock.group_stock_user`). Customers do not see this menu and cannot modify delivery status.

## List view

- **Backed by:** `sale.order`
- **Filter:** `state in ('sale', 'done')` (confirmed or done orders)
- **Columns:** Order number, Customer, Phone, Delivery address, Status (Mongolian label), Last status change time
- Native state/stock fields are hidden. Create/delete disabled.

## Form view (Delivery Workbench)

- **Read-only:** Customer, phone, delivery address, 5-step delivery timeline, status history
- **Action buttons:** Бэлтгэж байна, Бэлтгэж дууссан, Хүргэлтэд гарсан, Хүргэгдсэн
  - Call `order._mxm_set_status(...)`; respect allowed transitions; visible only when the transition is valid
- Create/delete disabled.

## Access control

- **mxm_delivery_status** is **read-only** on the model: editable only via Delivery Workbench buttons or API (staff).
- Only delivery/stock users see **Inguumel → Хүргэлт**. Customers never modify delivery status.

## Manual test

1. Log in as a user with **Inventory / User**.
2. Open **Inguumel → Хүргэлт**.
3. Confirm list shows confirmed sale orders with Order, Phone, Address, Status, Last Change.
4. Open a record → Delivery Workbench with timeline and one visible button (e.g. "Бэлтгэж байна" when status is received).
5. Click the button → status and timeline update; next button appears.
6. Log in as portal/customer → **Inguumel** menu is absent or **Хүргэлт** is not visible.
