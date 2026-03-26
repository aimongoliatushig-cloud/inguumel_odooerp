# -*- coding: utf-8 -*-
"""
Order flow: address and confirm (checkout → address → confirm).
POST /api/v1/orders/<id>/address – set delivery address (ownership validated).
POST /api/v1/orders/<id>/confirm – validate, set payment_method, confirm, return state + next_step.
"""
import json
import logging

from odoo import http
from odoo.exceptions import UserError, ValidationError, AccessError

from odoo.addons.inguumel_mobile_api.controllers.base import get_request_id, ok, fail

_logger = logging.getLogger(__name__)

# x_payment_method on sale.order: cod | qpay_pending | qpay_paid | card_paid | wallet_paid. API accepts cash → cod.
# Prepaid (qpay_paid, card_paid, wallet_paid): stock decreases on confirm. COD: reserve only; validate on delivered.
PAYMENT_METHODS_ALLOWED = frozenset([
    "cod", "cash", "qpay_pending", "qpay_paid", "card_paid", "wallet_paid",
])
PAYMENT_METHOD_TO_ORDER = {
    "cash": "cod",
    "cod": "cod",
    "qpay_pending": "qpay_pending",
    "qpay_paid": "qpay_paid",
    "card_paid": "card_paid",
    "wallet_paid": "wallet_paid",
}


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


def _get_order_for_customer(env, order_id, partner_id, request_id):
    """Load sale.order; must exist and belong to partner. Returns (order, error_response)."""
    SaleOrder = env["sale.order"].sudo()
    order = SaleOrder.browse(order_id)
    if not order.exists():
        _logger.info(
            "order_flow order not found order_id=%s request_id=%s",
            order_id,
            request_id,
            extra={"request_id": request_id},
        )
        return None, fail(
            message="Order not found",
            code="NOT_FOUND",
            http_status=404,
            request_id=request_id,
        )
    if order.partner_id.id != partner_id:
        _logger.info(
            "order_flow forbidden order_id=%s partner_id=%s user_partner_id=%s request_id=%s",
            order_id,
            order.partner_id.id,
            partner_id,
            request_id,
            extra={"request_id": request_id},
        )
        return None, fail(
            message="Order not found",
            code="NOT_FOUND",
            http_status=404,
            request_id=request_id,
        )
    return order, None


class OrderFlowAPI(http.Controller):
    """Order flow: address and confirm."""

    @http.route(
        "/api/v1/orders/<int:order_id>/address",
        type="http",
        auth="public",
        methods=["PUT", "POST"],
        csrf=False,
    )
    def set_address(self, order_id, **kwargs):
        """PUT/POST /api/v1/orders/<order_id>/address – set delivery address (owner only)."""
        request_id = get_request_id()
        try:
            user, err = _require_user(request_id)
            if err is not None:
                return err
            payload, err = _parse_json_body(http.request, request_id)
            if err is not None:
                return err
            payload = payload or {}

            order, err = _get_order_for_customer(
                http.request.env, order_id, user.partner_id.id, request_id
            )
            if err is not None:
                return err

            errors = {}
            delivery_address = payload.get("delivery_address")
            if delivery_address is not None:
                delivery_address = str(delivery_address).strip()
            else:
                delivery_address = ""
            if not delivery_address:
                errors["delivery_address"] = "required"

            if errors:
                _logger.info(
                    "order_flow.address validation failed order_id=%s errors=%s request_id=%s",
                    order_id,
                    errors,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail(
                    message="delivery_address is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                    errors=errors,
                )

            write_vals = {"x_delivery_address": delivery_address}
            if "phone_primary" in payload:
                write_vals["x_phone_primary"] = (payload.get("phone_primary") or "").strip()
            if "phone_secondary" in payload:
                write_vals["x_phone_secondary"] = (payload.get("phone_secondary") or "").strip()
            order.sudo().write(write_vals)
            _logger.info(
                "order_flow.address set order_id=%s request_id=%s",
                order_id,
                request_id,
                extra={"request_id": request_id},
            )
            return ok(
                data={"order_id": order.id, "order_number": order.name},
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "order_flow.address error order_id=%s request_id=%s: %s",
                order_id,
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

    @http.route(
        "/api/v1/orders/<int:order_id>/confirm",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def confirm_order(self, order_id, **kwargs):
        """POST /api/v1/orders/<order_id>/confirm – validate, set payment, confirm (COD → Захиалга авлаа).
        Uses action_confirm() for all orders (MXM and non-MXM) so delivery picking is created via procurement.
        Verify: curl -X POST "http://HOST:8069/api/v1/orders/<id>/confirm?warehouse_id=1" -H "Content-Type: application/json" -d '{"payment_method":"cod"}' -H "Authorization: Bearer TOKEN"
        Expect: HTTP 200, data.state=sale, data.next_step=received, outgoing picking with origin=order.name.
        """
        request_id = get_request_id()
        try:
            _logger.info(
                "order_flow.confirm called order_id=%s request_id=%s",
                order_id,
                request_id,
                extra={"request_id": request_id},
            )
            user, err = _require_user(request_id)
            if err is not None:
                return err
            payload, err = _parse_json_body(http.request, request_id)
            if err is not None:
                return err
            payload = payload or {}

            order, err = _get_order_for_customer(
                http.request.env, order_id, user.partner_id.id, request_id
            )
            if err is not None:
                return err

            errors = {}

            if order.state != "draft":
                errors["order"] = "already_confirmed"
            if not order.warehouse_id or not order.warehouse_id.exists():
                errors["warehouse_id"] = "missing"
            if not order.order_line:
                errors["order_line"] = "empty"
            amount_total = getattr(order, "amount_total", 0) or 0
            if amount_total <= 0:
                errors["amount_total"] = "must_be_positive"

            # Address required for delivery orders (this is a delivery flow)
            addr = (getattr(order, "x_delivery_address", None) or "").strip()
            if not addr and order.partner_id:
                partner_street = (getattr(order.partner_id, "street", None) or "").strip()
                if not partner_street:
                    errors["delivery_address"] = "required"

            payment_method_raw = (payload.get("payment_method") or "cod").strip().lower()
            if payment_method_raw not in PAYMENT_METHODS_ALLOWED:
                errors["payment_method"] = "invalid"
            payment_method = PAYMENT_METHOD_TO_ORDER.get(payment_method_raw, "cod")

            if errors:
                _logger.info(
                    "order_flow.confirm validation failed order_id=%s errors=%s request_id=%s",
                    order_id,
                    errors,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail(
                    message="Validation failed",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                    errors=errors,
                )

            # Set payment method on order
            order.sudo().write({"x_payment_method": payment_method})

            # Resolve warehouse: query param warehouse_id, else order.warehouse_id
            env = http.request.env
            raw_wh = kwargs.get("warehouse_id") or (
                getattr(http.request.httprequest, "args", {}).get("warehouse_id")
                if hasattr(http.request, "httprequest") else None
            )
            if raw_wh is not None:
                try:
                    warehouse_id = int(raw_wh)
                except (TypeError, ValueError):
                    warehouse_id = None
            else:
                warehouse_id = None
            if warehouse_id is not None:
                warehouse = env["stock.warehouse"].sudo().browse(warehouse_id).exists()
            else:
                warehouse = order.warehouse_id
            if not warehouse or not warehouse.exists():
                return fail(
                    message="warehouse_id is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                    errors={"warehouse_id": "required"},
                )

            partner = order.partner_shipping_id or order.partner_id
            if not partner:
                return fail(
                    message="Partner (shipping or order) is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                    errors={"partner": "required"},
                )

            # Defensive: set x_order_source from origin for MXM
            if not order.x_order_source and order.origin and "MXM" in (order.origin or ""):
                src = "mxm_cart" if "MXM Cart" in (order.origin or "") else "mxm_mobile"
                order.sudo().write({"x_order_source": src})

            mxm = (
                order.x_order_source in ("mxm_mobile", "mxm_cart")
                or ("MXM" in (order.origin or ""))
            )

            # Use action_confirm() for all (MXM and non-MXM) so picking is always created via procurement.
            order.sudo().action_confirm()
            if mxm:
                _logger.info(
                    "[ORDER_CONFIRM_MXM] order=%s id=%s wh=%s",
                    order.name,
                    order.id,
                    warehouse.id,
                    extra={"request_id": request_id},
                )

            # Hybrid stock policy: prepaid → validate picking now (On Hand decreases); COD → reserve only
            pickings = order.sudo()._mxm_get_outgoing_pickings()
            if pickings:
                if order.sudo()._mxm_is_prepaid():
                    ok_validate, err_validate = order.sudo()._mxm_validate_delivery_pickings()
                    if not ok_validate:
                        return fail(
                            message=err_validate or "Insufficient stock or could not validate delivery.",
                            code="VALIDATION_ERROR",
                            http_status=400,
                            request_id=request_id,
                            errors={"stock": err_validate},
                        )
                else:
                    # COD: only reserve (action_assign); do not validate
                    for picking in pickings:
                        if picking.state in ("confirmed", "waiting"):
                            try:
                                picking.action_assign()
                                picking.invalidate_recordset()
                            except (UserError, ValidationError) as e:
                                return fail(
                                    message="Insufficient stock to reserve for delivery.",
                                    code="VALIDATION_ERROR",
                                    http_status=400,
                                    request_id=request_id,
                                    errors={"stock": str(e)},
                                )
                        if picking.state not in ("assigned", "done"):
                            return fail(
                                message="Insufficient stock to reserve for delivery.",
                                code="VALIDATION_ERROR",
                                http_status=400,
                                request_id=request_id,
                                errors={"stock": "Reservation failed for %s" % (picking.name or picking.id)},
                            )

            # Ensure initial delivery status "received" (Захиалга авлаа)
            if not getattr(order, "mxm_delivery_status", None):
                try:
                    order.sudo()._mxm_ensure_initial_delivery_status()
                except Exception:
                    pass

            next_step = "received"
            _logger.info(
                "order_flow.confirm success order_id=%s state=%s request_id=%s",
                order_id,
                order.state,
                request_id,
                extra={"request_id": request_id},
            )
            return ok(
                data={
                    "order_id": order.id,
                    "order_number": order.name,
                    "state": order.state,
                    "next_step": next_step,
                    "delivery_status_code": getattr(order, "mxm_delivery_status", None) or "received",
                },
                request_id=request_id,
            )
        except (UserError, ValidationError) as e:
            _logger.warning(
                "order_flow.confirm validation/rule order_id=%s request_id=%s: %s",
                order_id,
                request_id,
                str(e),
                extra={"request_id": request_id},
            )
            return fail(
                message=str(e),
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
                errors={"order": str(e)},
            )
        except AccessError as e:
            _logger.warning(
                "order_flow.confirm access denied order_id=%s request_id=%s: %s",
                order_id,
                request_id,
                str(e),
                extra={"request_id": request_id},
            )
            return fail(
                message="Access denied",
                code="FORBIDDEN",
                http_status=403,
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "order_flow.confirm error order_id=%s request_id=%s: %s",
                order_id,
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

    @http.route(
        "/api/v1/orders/<int:order_id>/cancel",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def cancel_order(self, order_id, **kwargs):
        """POST /api/v1/orders/<order_id>/cancel – cancel order. If picking not done: unreserve. If done: create/validate return then cancel. Body: { "reason": "optional" }."""
        request_id = get_request_id()
        try:
            _logger.info(
                "order_flow.cancel called order_id=%s request_id=%s",
                order_id,
                request_id,
                extra={"request_id": request_id},
            )
            user, err = _require_user(request_id)
            if err is not None:
                return err
            payload, err = _parse_json_body(http.request, request_id)
            if err is not None:
                return err
            payload = payload or {}
            reason = (payload.get("reason") or "").strip() or None

            order, err = _get_order_for_customer(
                http.request.env, order_id, user.partner_id.id, request_id
            )
            if err is not None:
                return err

            if order.state == "cancel":
                return ok(
                    data={
                        "order_id": order.id,
                        "order_number": order.name,
                        "state": "cancel",
                        "delivery_status_code": "cancelled",
                        "cancelled": True,
                    },
                    message="Order already cancelled",
                    request_id=request_id,
                )

            ok_cancel, err_cancel = order.sudo()._mxm_cancel_order()
            if not ok_cancel:
                return fail(
                    message=err_cancel or "Cancellation failed",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                    errors={"cancel": err_cancel},
                )

            order.invalidate_recordset()
            _logger.info(
                "order_flow.cancel success order_id=%s request_id=%s reason=%s",
                order_id,
                request_id,
                reason or "(none)",
                extra={"request_id": request_id},
            )
            return ok(
                data={
                    "order_id": order.id,
                    "order_number": order.name,
                    "state": order.state,
                    "delivery_status_code": getattr(order, "mxm_delivery_status", None) or "cancelled",
                    "cancelled": True,
                },
                request_id=request_id,
            )
        except (UserError, ValidationError) as e:
            _logger.warning(
                "order_flow.cancel validation order_id=%s request_id=%s: %s",
                order_id,
                request_id,
                str(e),
                extra={"request_id": request_id},
            )
            return fail(
                message=str(e),
                code="VALIDATION_ERROR",
                http_status=400,
                request_id=request_id,
                errors={"cancel": str(e)},
            )
        except Exception as e:
            _logger.exception(
                "order_flow.cancel error order_id=%s request_id=%s: %s",
                order_id,
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
