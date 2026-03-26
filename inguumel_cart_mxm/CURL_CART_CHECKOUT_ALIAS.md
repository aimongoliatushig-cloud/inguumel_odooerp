# Cart checkout route alias – curl proof

## Change
- **POST /api/v1/cart/checkout** is now an alias of **POST /api/v1/mxm/cart/checkout** (same handler).
- Both routes accept `warehouse_id` as query param and return standard `{success, code, message, request_id, data}`.
- Order lines use **product_uom_id** (Odoo 19 sale.order.line); missing UoM on product returns 400 VALIDATION_ERROR.

## Curl test (must return 200 or 400, never 404)

```bash
# Replace host and token
HOST="http://localhost:8069"
TOKEN="<your_bearer_token>"

# 1) New alias – must NOT 404
curl -i -X POST "$HOST/api/v1/cart/checkout?warehouse_id=1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"

# Expected: 200 (if cart has lines) with body like:
# {"success": true, "code": "OK", "message": "OK", "request_id": "<uuid>", "data": {"order_id": ..., "order_number": ..., "name": ..., "state": "draft"}, "meta": null}
# Or 400 (e.g. cart empty): {"success": false, "code": "VALIDATION_ERROR", "message": "Cart is empty", "request_id": "<uuid>", ...}
# Or 401 if no/invalid token.

# 2) Legacy route still works
curl -i -X POST "$HOST/api/v1/mxm/cart/checkout?warehouse_id=1" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json"
```

## Other /api/v1 routes (no alias needed)
- **PUT/POST /api/v1/orders/<id>/address** – already under /api/v1
- **POST /api/v1/orders/<id>/confirm** – already under /api/v1
