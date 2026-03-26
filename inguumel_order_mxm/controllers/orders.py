# -*- coding: utf-8 -*-
"""
POST /api/v1/mxm/orders – create sale order and outgoing delivery picking (no routes/MTO/Transit).
MXM API orders get a direct stock.picking WH/Stock -> Customer; SO state set to 'sale'. Consistent JSON.
"""
import json
import logging

from odoo import http, _
from odoo.http import request
from odoo.exceptions import UserError

from odoo.addons.inguumel_mobile_api.controllers.base import (
    get_request_id,
    ok,
    fail,
)

_logger = logging.getLogger(__name__)

QTY_MAX = 999
ITEMS_LIMIT = 50


def _get_warehouse_from_request(env, user, payload, request_id):
    """Resolve warehouse_id from payload or user/company fallback. Returns (warehouse, error_response or None)."""
    raw = payload.get("warehouse_id")
    if raw is not None and raw != "":
        try:
            wid = int(raw)
        except (TypeError, ValueError):
            return None, fail(
                message="warehouse_id must be an integer",
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
            )
        Warehouse = env["stock.warehouse"].sudo()
        warehouse = Warehouse.browse(wid)
        if not warehouse.exists():
            return None, fail(
                message="Warehouse not found",
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
            )
        if warehouse.company_id.id != user.company_id.id:
            return None, fail(
                message="Warehouse does not belong to your company",
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
            )
        return warehouse, None
    warehouse = getattr(user, "property_warehouse_id", None) or getattr(user, "warehouse_id", None)
    if not warehouse or not warehouse.exists():
        warehouse = env["stock.warehouse"].search(
            [("company_id", "=", user.company_id.id)], limit=1
        )
    if not warehouse:
        return None, fail(
            message="No warehouse available for your company",
            code="VALIDATION_ERROR",
            http_status=400,
            request_id=request_id,
        )
    return warehouse, None


class OrderMXMAPI(http.Controller):
    """MXM order creation endpoint."""

    @http.route(
        "/api/v1/mxm/orders",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def create_order(self, **kwargs):
        """POST /api/v1/mxm/orders – create and confirm sale order from JSON body."""
        request_id = get_request_id()
        try:
            user = http.request.env.user
            if not user or user._is_public():
                return fail(
                    message="Unauthorized",
                    code="UNAUTHORIZED",
                    http_status=401,
                    request_id=request_id,
                )

            body = http.request.httprequest.get_data(as_text=True) or "{}"
            try:
                payload = json.loads(body)
            except (TypeError, ValueError):
                payload = {}
            items = payload.get("items") if isinstance(payload.get("items"), list) else None

            if not items:
                return fail(
                    message="items is required and must be a non-empty array",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            if len(items) > ITEMS_LIMIT:
                return fail(
                    message="items must not exceed %d lines" % ITEMS_LIMIT,
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )

            env = http.request.env
            warehouse, err = _get_warehouse_from_request(env, user, payload, request_id)
            if err is not None:
                return err

            # Force 1-step delivery route so procurement uses WH/Stock -> Customers, not Transit.
            route = None
            if warehouse.delivery_route_id and warehouse.delivery_route_id.exists():
                route = warehouse.delivery_route_id
            if not route or not getattr(route, "sale_selectable", True):
                r3 = env["stock.route"].sudo().browse(3)
                if r3.exists() and r3.active:
                    route = r3
            route_ids_cmd = [(6, 0, [route.id])] if route else []

            Product = env["product.product"].sudo()
            SaleOrder = env["sale.order"]

            order_lines = []
            for idx, row in enumerate(items):
                if not isinstance(row, dict):
                    return fail(
                        message="items[%d] must be an object with product_id and qty" % idx,
                        code="VALIDATION_ERROR",
                        http_status=400,
                        request_id=request_id,
                    )
                try:
                    product_id = int(row.get("product_id"))
                except (TypeError, ValueError):
                    return fail(
                        message="items[%d].product_id is required and must be an integer" % idx,
                        code="VALIDATION_ERROR",
                        http_status=400,
                        request_id=request_id,
                    )
                try:
                    qty = float(row.get("qty", 0))
                except (TypeError, ValueError):
                    qty = 0
                if qty <= 0:
                    return fail(
                        message="items[%d].qty must be a positive number" % idx,
                        code="VALIDATION_ERROR",
                        http_status=400,
                        request_id=request_id,
                    )
                if qty > QTY_MAX:
                    return fail(
                        message="items[%d].qty must not exceed %s" % (idx, QTY_MAX),
                        code="VALIDATION_ERROR",
                        http_status=400,
                        request_id=request_id,
                    )
                product = Product.browse(product_id)
                if not product.exists():
                    return fail(
                        message="items[%d]: product_id %s not found" % (idx, product_id),
                        code="VALIDATION_ERROR",
                        http_status=400,
                        request_id=request_id,
                    )
                if not product.sale_ok:
                    return fail(
                        message="items[%d]: product %s is not sellable" % (idx, product_id),
                        code="VALIDATION_ERROR",
                        http_status=400,
                        request_id=request_id,
                    )
                price_unit = product.list_price
                if isinstance(row.get("price_unit"), (int, float)):
                    price_unit = float(row["price_unit"])
                line_vals = {
                    "product_id": product.id,
                    "product_uom_qty": qty,
                    "product_uom_id": product.uom_id.id,
                    "price_unit": price_unit,
                }
                if route_ids_cmd:
                    line_vals["route_ids"] = route_ids_cmd
                order_lines.append((0, 0, line_vals))

            partner_id = user.partner_id.id
            order_vals = {
                "partner_id": partner_id,
                "company_id": warehouse.company_id.id,
                "warehouse_id": warehouse.id,
                "order_line": order_lines,
                "origin": "MXM API",
                "x_order_source": "mxm_mobile",
            }

            # B: Before create – log request_id, warehouse_id, chosen route.
            _logger.info(
                "[MXM_ORDER_DIAG] request_id=%s before_create warehouse_id=%s route_id=%s",
                request_id,
                warehouse.id,
                route.id if route else None,
                extra={"request_id": request_id},
            )

            # All-or-nothing: create order + direct outgoing picking (no action_confirm / no routes).
            with env.cr.savepoint():
                order = SaleOrder.with_company(user.company_id).sudo().create(order_vals)

                # Defensive: ensure x_order_source set (order_vals already has mxm_mobile)
                if not order.x_order_source and order.origin and "MXM" in (order.origin or ""):
                    order.sudo().write({"x_order_source": "mxm_mobile"})
                    _logger.info("[MXM_ORDER] set x_order_source=mxm_mobile for order %s", order.name)

                _logger.info(
                    "[MXM_ORDER_DIAG] request_id=%s after_create order_id=%s order_name=%s",
                    request_id,
                    order.id,
                    order.name or "",
                    extra={"request_id": request_id},
                )

                # Confirm order (MXM and non-MXM): action_confirm() creates picking via procurement.
                if route:
                    for line in order.order_line:
                        if line.route_ids.ids != [route.id]:
                            line.sudo().write({"route_ids": [(6, 0, [route.id])]})
                try:
                    order.sudo().action_confirm()
                except Exception as confirm_err:
                    _logger.exception(
                        "[MXM_ORDER_DIAG] request_id=%s action_confirm failed: %s",
                        request_id,
                        confirm_err,
                        extra={"request_id": request_id},
                    )
                    raise UserError(str(confirm_err))
                outgoing = order.picking_ids.filtered(
                    lambda p: p.picking_type_id and p.picking_type_id.code == "outgoing"
                )
                if not outgoing:
                    raise UserError(
                        "Delivery picking was not created. Check stock rules and routes."
                    )
                first_picking = outgoing[0]
                if order.x_order_source in ("mxm_mobile", "mxm_cart"):
                    _logger.info(
                        "[MXM_PICKING] outgoing picking=%s order=%s wh=%s request_id=%s",
                        first_picking.id,
                        order.name,
                        warehouse.id,
                        request_id,
                        extra={"request_id": request_id},
                    )
                return ok(
                    data={
                        "order_id": order.id,
                        "order_name": order.name,
                        "order_number": order.name,
                        "picking_id": first_picking.id,
                        "picking_name": first_picking.name,
                        "state": order.state,
                    },
                    request_id=request_id,
                )
        except UserError as e:
            _logger.warning(
                "mxm.orders create UserError: %s request_id=%s", str(e), request_id
            )
            return fail(
                message=str(e),
                code="NO_PICKING_CREATED",
                http_status=422,
                request_id=request_id,
                data={"message_mn": "Хүргэлтийн бичилт үүсгэгдээгүй."},
            )
        except Exception as e:
            _logger.exception(
                "mxm.orders create error: %s request_id=%s", e, request_id
            )
            return fail(
                message="Internal error",
                code="ERROR",
                http_status=500,
                request_id=request_id,
                data={"message_mn": "Дотоод алдаа."},
            )
