# -*- coding: utf-8 -*-
"""
MXM Cart API: GET/POST/PATCH/DELETE cart and lines, checkout.
Warehouse-scoped, session-based (requires logged-in user).
"""
import json
import logging

from odoo import http

from odoo.addons.inguumel_mobile_api.controllers.base import (
    get_request_id,
    ok,
    fail,
)

_logger = logging.getLogger(__name__)


def _parse_json_body(request, request_id):
    """Parse JSON body. Returns (data, error_response)."""
    ct = (request.httprequest.content_type or "").strip().lower()
    if "application/json" not in ct:
        return None, fail(
            message="Content-Type must be application/json",
            code="INVALID_JSON",
            http_status=400,
            request_id=request_id,
        )
    raw = request.httprequest.get_data(as_text=True)
    if not raw or not raw.strip():
        return {}, None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None, fail(
            message="Invalid JSON",
            code="INVALID_JSON",
            http_status=400,
            request_id=request_id,
        )
    if not isinstance(data, dict):
        return None, fail(
            message="Invalid JSON",
            code="INVALID_JSON",
            http_status=400,
            request_id=request_id,
        )
    return data, None


def _require_user(request_id):
    """Return 401 if public user."""
    user = http.request.env.user
    if not user or user._is_public():
        return None, fail(
            message="Unauthorized",
            code="UNAUTHORIZED",
            http_status=401,
            request_id=request_id,
        )
    return user, None


def _get_warehouse(env, user, warehouse_id_param=None):
    """
    Warehouse selection priority:
    1. Request param warehouse_id (from mobile)
    2. partner.x_default_warehouse_id (from location flow)
    3. user.property_warehouse_id
    4. user.warehouse_id
    5. Company warehouse
    """
    Warehouse = env["stock.warehouse"].sudo()
    if warehouse_id_param is not None and warehouse_id_param != "":
        try:
            wh_id = int(warehouse_id_param)
            wh = Warehouse.browse(wh_id)
            if wh.exists() and wh.company_id == user.company_id:
                return wh
        except (TypeError, ValueError):
            pass
    partner = user.partner_id
    wh = getattr(partner, "x_default_warehouse_id", None)
    if wh and wh.exists():
        return wh
    wh = getattr(user, "property_warehouse_id", None) or getattr(user, "warehouse_id", None)
    if wh and wh.exists():
        return wh
    wh = Warehouse.search([("company_id", "=", user.company_id.id)], limit=1)
    return wh


def _get_available_qty(env, product_id, warehouse):
    """Available qty for product in warehouse (lot_stock and children)."""
    if not warehouse or not warehouse.lot_stock_id:
        return 0.0
    loc = warehouse.lot_stock_id
    quants = env["stock.quant"].sudo().read_group(
        [
            ("location_id", "child_of", loc.id),
            ("product_id", "=", product_id),
        ],
        ["quantity:sum", "reserved_quantity:sum"],
        [],
    )
    if not quants:
        return 0.0
    q = quants[0]
    return (q.get("quantity") or 0) - (q.get("reserved_quantity") or 0)


def _cart_response(cart, request_id):
    """Build API response for cart (cart_id, warehouse_id, items, total_qty, total_amount)."""
    if not cart:
        return ok(
            data={
                "cart_id": None,
                "warehouse_id": None,
                "items": [],
                "total_qty": 0,
                "total_amount": 0,
            },
            request_id=request_id,
        )
    items = []
    total_qty = 0.0
    total_amount = 0.0
    for line in cart.line_ids:
        product = line.product_id
        write_date_str = product.write_date.isoformat() if product.write_date else ""
        image_url = None
        if getattr(product, "image_1920", None) or getattr(product, "image_512", None):
            image_url = "/api/v1/mxm/product-image/%s?size=512&v=%s" % (
                product.id,
                write_date_str,
            )
        items.append({
            "line_id": line.id,
            "product_id": product.id,
            "name": product.display_name,
            "qty": line.product_uom_qty,
            "price": line.price_unit,
            "subtotal": line.price_subtotal,
            "image_url": image_url,
        })
        total_qty += line.product_uom_qty
        total_amount += line.price_subtotal
    return ok(
        data={
            "cart_id": cart.id,
            "warehouse_id": cart.warehouse_id.id,
            "items": items,
            "total_qty": total_qty,
            "total_amount": total_amount,
        },
        request_id=request_id,
    )


class CartMXMAPI(http.Controller):
    """MXM Cart API."""

    @http.route(
        "/api/v1/mxm/cart",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def get_cart(self, warehouse_id=None, **kwargs):
        """GET /api/v1/mxm/cart – get or create cart for current user + warehouse."""
        request_id = get_request_id()
        user, err = _require_user(request_id)
        if err is not None:
            return err
        env = http.request.env
        warehouse = _get_warehouse(env, user, warehouse_id)
        if not warehouse:
            return fail(
                message="No warehouse available",
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
            )
        Cart = env["mxm.cart"].sudo()
        cart = Cart.get_or_create(user.partner_id.id, warehouse.id)
        return _cart_response(cart, request_id)

    @http.route(
        "/api/v1/mxm/cart/lines",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def add_line(self, warehouse_id=None, **kwargs):
        """POST /api/v1/mxm/cart/lines – add item (or increment qty if exists)."""
        request_id = get_request_id()
        user, err = _require_user(request_id)
        if err is not None:
            return err
        payload, err = _parse_json_body(http.request, request_id)
        if err is not None:
            return err
        try:
            product_id = int(payload.get("product_id"))
        except (TypeError, ValueError):
            return fail(
                message="product_id is required and must be an integer",
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
            )
        try:
            qty = float(payload.get("qty", 1))
        except (TypeError, ValueError):
            qty = 1.0
        if qty <= 0:
            return fail(
                message="qty must be positive",
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
            )
        env = http.request.env
        warehouse = _get_warehouse(env, user, payload.get("warehouse_id") or warehouse_id)
        if not warehouse:
            return fail(
                message="No warehouse available",
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
            )
        Product = env["product.product"].sudo()
        product = Product.browse(product_id)
        if not product.exists():
            return fail(
                message="Product not found",
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
            )
        if not product.sale_ok:
            return fail(
                message="Product is not sellable",
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
            )
        available = _get_available_qty(env, product_id, warehouse)
        Cart = env["mxm.cart"].sudo()
        cart = Cart.get_or_create(user.partner_id.id, warehouse.id)
        existing = cart.line_ids.filtered(lambda l: l.product_id.id == product_id)
        new_qty = (existing.product_uom_qty if existing else 0) + qty
        if new_qty > available:
            return fail(
                message="Insufficient stock (available: %s)" % int(available),
                code="INSUFFICIENT_STOCK",
                http_status=400,
                request_id=request_id,
            )
        price_unit = product.lst_price
        if existing:
            existing.write({"product_uom_qty": new_qty, "price_unit": price_unit})
        else:
            env["mxm.cart.line"].sudo().create({
                "cart_id": cart.id,
                "product_id": product_id,
                "product_uom_qty": qty,
                "price_unit": price_unit,
            })
        cart.invalidate_recordset()
        return _cart_response(cart, request_id)

    @http.route(
        "/api/v1/mxm/cart/lines/<int:line_id>",
        type="http",
        auth="public",
        methods=["PATCH"],
        csrf=False,
    )
    def update_line(self, line_id, **kwargs):
        """PATCH /api/v1/mxm/cart/lines/<line_id> – update qty."""
        request_id = get_request_id()
        user, err = _require_user(request_id)
        if err is not None:
            return err
        payload, err = _parse_json_body(http.request, request_id)
        if err is not None:
            return err
        try:
            qty = float(payload.get("qty", 0))
        except (TypeError, ValueError):
            return fail(
                message="qty is required and must be a number",
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
            )
        if qty <= 0:
            return fail(
                message="qty must be positive",
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
            )
        env = http.request.env
        Line = env["mxm.cart.line"].sudo()
        line = Line.browse(line_id)
        if not line.exists():
            return fail(
                message="Line not found",
                code="NOT_FOUND",
                http_status=404,
                request_id=request_id,
            )
        cart = line.cart_id
        if cart.partner_id.id != user.partner_id.id:
            return fail(
                message="Unauthorized",
                code="UNAUTHORIZED",
                http_status=401,
                request_id=request_id,
            )
        warehouse = cart.warehouse_id
        available = _get_available_qty(env, line.product_id.id, warehouse)
        if qty > available:
            return fail(
                message="Insufficient stock (available: %s)" % int(available),
                code="INSUFFICIENT_STOCK",
                http_status=400,
                request_id=request_id,
            )
        line.write({"product_uom_qty": qty})
        return _cart_response(cart, request_id)

    @http.route(
        "/api/v1/mxm/cart/lines/<int:line_id>",
        type="http",
        auth="public",
        methods=["DELETE"],
        csrf=False,
    )
    def remove_line(self, line_id, **kwargs):
        """DELETE /api/v1/mxm/cart/lines/<line_id> – remove item."""
        request_id = get_request_id()
        user, err = _require_user(request_id)
        if err is not None:
            return err
        env = http.request.env
        Line = env["mxm.cart.line"].sudo()
        line = Line.browse(line_id)
        if not line.exists():
            return fail(
                message="Line not found",
                code="NOT_FOUND",
                http_status=404,
                request_id=request_id,
            )
        cart = line.cart_id
        if cart.partner_id.id != user.partner_id.id:
            return fail(
                message="Unauthorized",
                code="UNAUTHORIZED",
                http_status=401,
                request_id=request_id,
            )
        line.unlink()
        return _cart_response(cart, request_id)

    @http.route(
        "/api/v1/mxm/cart",
        type="http",
        auth="public",
        methods=["DELETE"],
        csrf=False,
    )
    def clear_cart(self, warehouse_id=None, **kwargs):
        """DELETE /api/v1/mxm/cart – clear all lines (cart record kept)."""
        request_id = get_request_id()
        user, err = _require_user(request_id)
        if err is not None:
            return err
        env = http.request.env
        warehouse = _get_warehouse(env, user, warehouse_id)
        if not warehouse:
            return fail(
                message="No warehouse available",
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
            )
        Cart = env["mxm.cart"].sudo()
        cart = Cart.get_or_create(user.partner_id.id, warehouse.id)
        cart.line_ids.unlink()
        return _cart_response(cart, request_id)

    @http.route(
        "/api/v1/cart/checkout",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    @http.route(
        "/api/v1/mxm/cart/checkout",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def checkout(self, warehouse_id=None, **kwargs):
        """POST /api/v1/cart/checkout (alias) and /api/v1/mxm/cart/checkout – create DRAFT sale order from cart, return order_id; clear cart."""
        request_id = get_request_id()
        try:
            user, err = _require_user(request_id)
            if err is not None:
                return err
            env = http.request.env
            warehouse = _get_warehouse(env, user, warehouse_id)
            if not warehouse:
                return fail(
                    message="No warehouse available",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            Cart = env["mxm.cart"].sudo()
            cart = Cart.get_or_create(user.partner_id.id, warehouse.id)
            if not cart.line_ids:
                return fail(
                    message="Cart is empty",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            SaleOrder = env["sale.order"].sudo()
            order_lines = []
            for line in cart.line_ids:
                if line.product_uom_qty <= 0:
                    continue
                product = line.product_id
                if not product or not product.exists():
                    continue
                uom = product.uom_id
                if not uom or not uom.exists():
                    return fail(
                        message="Missing UoM for product",
                        code="VALIDATION_ERROR",
                        http_status=400,
                        request_id=request_id,
                        errors={"product_uom_id": "Missing UoM for product %s" % (product.display_name or product.id)},
                    )
                order_lines.append((0, 0, {
                 "product_id": product.id,
                 "product_uom_id": uom.id,
                 "product_uom_qty": line.product_uom_qty,
                 "price_unit": line.price_unit,
                }))

            if not order_lines:
                return fail(
                    message="Cart has no valid lines",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            order_vals = {
                "partner_id": user.partner_id.id,
                "company_id": warehouse.company_id.id,
                "warehouse_id": warehouse.id,
                "order_line": order_lines,
                "origin": "MXM Cart",
            }
            order = SaleOrder.create(order_vals)
            cart.line_ids.unlink()
            _logger.info(
                "cart.checkout draft order_id=%s request_id=%s",
                order.id,
                request_id,
                extra={"request_id": request_id, "order_id": order.id},
            )
            return ok(
                data={
                    "order_id": order.id,
                    "order_number": order.name,
                    "name": order.name,
                    "state": order.state,
                },
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "cart.checkout error request_id=%s: %s",
                request_id,
                e,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="SERVER_ERROR",
                http_status=500,
                request_id=request_id,
            )
