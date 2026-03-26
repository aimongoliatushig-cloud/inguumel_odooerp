# Test: Order exists but warehouse mismatch -> 403 FORBIDDEN (not NOT_FOUND)

The driver API must return **403 FORBIDDEN** when the order exists but is not in the driver's warehouse scope (e.g. order has `warehouse_id=2`, driver has `x_warehouse_ids=[1]`). It must **not** return 404 NOT_FOUND in that case.

## Manual test

1. Use a driver user with `x_warehouse_ids = [1]` (only warehouse 1).
2. Pick a sale order that exists and has `warehouse_id = 2` (or any warehouse not in the driver's list). Note its ID as `ORDER_ID_OTHER_WH`.
3. Login and get token:
   ```bash
   TOKEN=$(curl -s -X POST "$BASE/api/v1/driver/auth/login" \
     -H "Content-Type: application/json" \
     -d '{"login":"driver1","password":"YOUR_PASSWORD"}' | jq -r '.data.access_token')
   ```
4. POST delivery status for the other-warehouse order:
   ```bash
   curl -s -X POST "$BASE/api/v1/driver/orders/ORDER_ID_OTHER_WH/delivery/status" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"status":"preparing"}' | jq .
   ```
5. **Expected:** HTTP 403, `success: false`, `code: "FORBIDDEN"` (not `NOT_FOUND`).

## Assertion

- If the response has `code: "NOT_FOUND"` then the fix is wrong: scope mismatch must return FORBIDDEN.
- If the response has HTTP 403 and `code: "FORBIDDEN"`, the behaviour is correct.
