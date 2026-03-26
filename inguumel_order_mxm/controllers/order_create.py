# -*- coding: utf-8 -*-
"""POST /api/v1/mxm/order/create – Place order from cart."""
import json
import logging
from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.addons.inguumel_mobile_api.controllers.base import get_request_id, ok, fail
from odoo.addons.inguumel_order_mxm.services.order_service import OrderCreateError

_logger = logging.getLogger(__name__)
ORDER_CREATE_DISABLED_KEY = "api_disabled:/api/v1/mxm/order/create"
ORDER_AUTO_CONFIRM_KEY = "mxm_order.auto_confirm"
PAYMENT_METHODS = frozenset(["cod", "qpay_pending"])


def _parse_json_body(request, request_id):
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
    user = http.request.env.user
    if not user or user._is_public():
        return None, fail(
            message="Unauthorized",
            code="UNAUTHORIZED",
            http_status=401,
            request_id=request_id,
        )
    return user, None


def _check_kill_switch(env, request_id):
    try:
        ICP = env["ir.config_parameter"].sudo()
        if ICP.get_param(ORDER_CREATE_DISABLED_KEY) in ("1", "true", "True"):
            return fail(
                message="Order creation is temporarily disabled",
                code="SERVICE_UNAVAILABLE",
                http_status=503,
                request_id=request_id,
            )
    except Exception:
        pass
    return None


class OrderCreateAPI(http.Controller):

    @http.route(
        "/api/v1/mxm/order/create",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def create(self, **kwargs):
        request_id = get_request_id()
        order_created = None
        try:
            _logger.info("order.create called", extra={"request_id": request_id})
            user, err = _require_user(request_id)
            if err is not None:
                return err
            env = http.request.env
            err = _check_kill_switch(env, request_id)
            if err is not None:
                return err
            payload, err = _parse_json_body(http.request, request_id)
            if err is not None:
                return err
            payload = payload or {}
            errors_map = {}
            phone_primary = payload.get("phone_primary")
            if not phone_primary or not str(phone_primary).strip():
                errors_map["phone_primary"] = "required"
            delivery_address = payload.get("delivery_address")
            if not delivery_address or not str(delivery_address).strip():
                errors_map["delivery_address"] = "required"

            # warehouse_id: from query params first, then JSON body, then fallback to cart
            warehouse_id = kwargs.get("warehouse_id")
            if warehouse_id is None or warehouse_id == "":
                warehouse_id = payload.get("warehouse_id")
            cart = None
            if warehouse_id is not None and warehouse_id != "":
                try:
                    warehouse_id = int(warehouse_id)
                except (TypeError, ValueError):
                    errors_map["warehouse_id"] = "must be integer"
                    warehouse_id = None
            else:
                # Fallback: find partner's cart with items
                Cart = env["mxm.cart"].sudo()
                cart = Cart.search(
                    [("partner_id", "=", user.partner_id.id)],
                    order="write_date desc",
                    limit=10,
                )
                cart = cart.filtered(lambda c: c.line_ids)[:1]
                warehouse_id = cart.warehouse_id.id if cart else None

            if not warehouse_id:
                errors_map["warehouse_id"] = "required"

            payment_method = (payload.get("payment_method") or "cod").strip().lower()
            if payment_method not in PAYMENT_METHODS:
                errors_map["payment_method"] = "must be 'cod' or 'qpay_pending'"

            if errors_map:
                code = "PHONE_REQUIRED" if "phone_primary" in errors_map else (
                    "ADDRESS_REQUIRED" if "delivery_address" in errors_map else (
                    "WAREHOUSE_REQUIRED" if "warehouse_id" in errors_map else "VALIDATION_ERROR"
                ))
                msg = "phone_primary is required" if "phone_primary" in errors_map else (
                    "delivery_address is required" if "delivery_address" in errors_map else (
                    "warehouse_id is required" if "warehouse_id" in errors_map else (
                    "payment_method " + errors_map.get("payment_method", "") if "payment_method" in errors_map else "Validation failed"
                )))
                return fail(
                    message=msg,
                    code=code,
                    http_status=400,
                    request_id=request_id,
                    errors=errors_map,
                )
            phone_secondary = payload.get("phone_secondary")
            auto_confirm = True
            try:
                ICP = env["ir.config_parameter"].sudo()
                val = ICP.get_param(ORDER_AUTO_CONFIRM_KEY, "1")
                auto_confirm = val in ("1", "true", "True", "yes")
            except Exception:
                pass
            OrderService = env["inguumel.order.service"]
            order = OrderService.create_order_from_cart(
                partner_id=user.partner_id.id,
                warehouse_id=warehouse_id,
                phone_primary=str(phone_primary).strip(),
                phone_secondary=phone_secondary,
                delivery_address=str(delivery_address).strip(),
                payment_method=payment_method,
                auto_confirm=auto_confirm,
                request_id=request_id,
            )
            order_created = order
            api_status = "confirmed" if order.state == "sale" else "processing"
            _logger.info(
                "order.create success user_id=%s order_id=%s status=%s request_id=%s",
                user.id,
                order.id,
                api_status,
                request_id,
                extra={"request_id": request_id, "order_id": order.id},
            )
            payment_method_val = getattr(order, "x_payment_method", None) or "cod"
            paid = False
            payment_status = "cod_pending" if payment_method_val == "cod" else "unpaid"
            return ok(
                data={
                    "id": order.id,
                    "name": order.name,
                    "status": api_status,
                    "order_id": order.id,
                    "order_number": order.name,
                    "paid": paid,
                    "payment_status": payment_status,
                    "payment_method": payment_method_val,
                },
                request_id=request_id,
            )
        except OrderCreateError as e:
            _logger.warning(
                "order.create validation: %s code=%s request_id=%s",
                e.message,
                e.code,
                request_id,
                extra={"request_id": request_id, "code": e.code},
            )
            errors = {"cart": e.message} if e.code == "CART_EMPTY" else None
            return fail(
                message=e.message,
                code=e.code,
                http_status=400,
                request_id=request_id,
                errors=errors,
            )
        except (UserError, ValidationError) as e:
            _logger.warning(
                "order.create validation/rule: %s request_id=%s",
                str(e),
                request_id,
                extra={"request_id": request_id},
            )
            return fail(
                message=str(e),
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
                errors={"order": str(e)},
            )
        except Exception as e:
            if order_created and order_created.exists():
                api_status = "confirmed" if order_created.state == "sale" else "processing"
                _logger.warning(
                    "order.create post-creation error, returning order_id: %s order_id=%s request_id=%s",
                    e,
                    order_created.id,
                    request_id,
                    extra={"request_id": request_id},
                )
                return ok(
                    data={
                        "id": order_created.id,
                        "name": order_created.name,
                        "status": api_status,
                        "order_id": order_created.id,
                        "order_number": order_created.name,
                    },
                    request_id=request_id,
                )
            _logger.exception(
                "order.create error: %s request_id=%s",
                e,
                request_id,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="SERVER_ERROR",
                http_status=500,
                request_id=request_id,
            )
