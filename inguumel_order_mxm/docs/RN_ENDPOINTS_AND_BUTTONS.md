# React Native: Correct Endpoints and Button Conditions

## Problem

- **GET /api/v1/orders/<id>** does **not** exist → 404 HTML. Do **not** use this URL.
- Auth was returning `role="warehouse_owner"` for both driver and cashier → buttons did not show by role.

## Backend fixes (done)

1. **Role mapping** (POST /api/v1/auth/login and driver auth):
   - Driver user (e.g. in group **Driver**) → `data.role === "driver"`
   - Cashier user (e.g. in group **Cash Confirm (Cashier)**) → `data.role === "cashier"`
   - Warehouse owner (no driver/cashier) → `data.role === "warehouse_owner"`
   - Admin → `data.role === "admin"`
   - Staff → `data.role === "staff"`
   - Customer → `data.role === "customer"`

2. **Correct order detail and delivery endpoints** (use these in RN):

| App / screen      | Order detail                    | Delivery status (read)              | Delivery status (set)                    | Cash confirm        |
|-------------------|----------------------------------|-------------------------------------|-------------------------------------------|---------------------|
| **General mobile**| GET /api/v1/mxm/orders/<id>     | GET /api/v1/orders/<id>/delivery    | (no button for customer)                  | (no)                |
| **Cashier / POS** | GET /api/v1/mxm/orders/<id>     | GET /api/v1/orders/<id>/delivery    | (optional)                                | POST .../cash-confirm |
| **Driver app**    | GET /api/v1/driver/orders/<id>  | GET /api/v1/driver/orders/<id>/delivery | POST /api/v1/driver/orders/<id>/delivery/status | (no)             |

## RN changes required

### 1) Order detail – stop using GET /api/v1/orders/<id>

- **General / Cashier:** Use **GET /api/v1/mxm/orders/<id>** (Bearer).
- **Driver app:** Use **GET /api/v1/driver/orders/<id>** (Bearer).

Replace any call to `GET /api/v1/orders/<orderId>` with the correct one above so you no longer get 404.

### 2) Cashier: “Төлбөр баталгаажуулах” (Cash Confirm) button

- **Show button only when:**
  - `role === "cashier"` (or `role === "admin"`) **and**
  - `order.payment_method_code === "cod"` (or `order.x_payment_method === "cod"`) **and**
  - `order.is_paid === false` (or `order.x_paid === false`).
- **On press:**  
  **POST /api/v1/orders/<orderId>/cash-confirm**  
  Body: `{}`  
  Headers: `Authorization: Bearer <token>`, `Content-Type: application/json`
- Do **not** show the button for other roles (e.g. do not show for `role === "driver"`).

### 3) Driver: delivery status change buttons

- **Show status buttons only when:**  
  `role === "driver"` (or `role === "warehouse_owner"` for backward compat).
- **Read current status:**  
  **GET /api/v1/driver/orders/<orderId>/delivery**  
  Use `data.current_status.code` and `data.timeline` for the next allowed statuses.
- **On press (e.g. “Хүргэлтэд гарсан” / “Delivered”):**  
  **POST /api/v1/driver/orders/<orderId>/delivery/status**  
  Body: `{ "status": "out_for_delivery" }` or `{ "status": "delivered" }`, etc.  
  Headers: `Authorization: Bearer <token>`, `Content-Type: application/json`

### 4) Delivery read (shared)

- **GET /api/v1/orders/<id>/delivery** works for both cashier and driver (owner or warehouse scope).
- Driver app can use **GET /api/v1/driver/orders/<id>/delivery** for the same payload with warehouse scope enforced.

## Odoo setup for roles

- **Driver (e.g. phone 00000000):**  
  User must be in group **Inguumel Order → Driver** and have **Warehouses** (x_warehouse_ids) set.
- **Cashier (e.g. phone 00000001):**  
  User must be in group **Inguumel Order → Cash Confirm (Cashier)**.
- Existing warehouse-only users stay in **Warehouse Owner**; they get `role="warehouse_owner"` and can still use driver app if they have warehouses.

## Verification (curl)

See `scripts/verify_role_and_endpoints.sh` (or run the curl commands from COD_CASH_CONFIRM_FLOW.md and DRIVER_API.md).
