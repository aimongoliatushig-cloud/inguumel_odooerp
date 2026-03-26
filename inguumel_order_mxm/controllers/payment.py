# -*- coding: utf-8 -*-
"""
QPay callback: confirm order only after payment success.
POST /api/v1/mxm/payment/qpay/callback
"""
import json
import logging
from odoo import http
from odoo.addons.inguumel_mobile_api.controllers.base import get_request_id, ok, fail

_logger = logging.getLogger(__name__)

QPAY_CALLBACK_DISABLED_KEY = "api_disabled:/api/v1/mxm/payment/qpay/callback"


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


class PaymentQPayCallback(http.Controller):
    """QPay payment callback – confirm order only after payment success."""

    @http.route(
        "/api/v1/mxm/payment/qpay/callback",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def qpay_callback(self, **kwargs):
        """
        POST /api/v1/mxm/payment/qpay/callback
        Body: { "order_id": 123 } or { "order_number": "S00005" }, "status": "success"|"failed", "transaction_id": "..." (optional)
        On status=success: find draft order with x_payment_method=qpay_pending and call action_confirm().
        """
        request_id = get_request_id()
        try:
            _logger.info(
                "payment.qpay_callback called request_id=%s",
                request_id,
                extra={"request_id": request_id},
            )
            env = http.request.env

            try:
                ICP = env["ir.config_parameter"].sudo()
                if ICP.get_param(QPAY_CALLBACK_DISABLED_KEY) in ("1", "true", "True"):
                    return fail(
                        message="QPay callback is disabled",
                        code="SERVICE_UNAVAILABLE",
                        http_status=503,
                        request_id=request_id,
                    )
            except Exception:
                pass

            payload, err = _parse_json_body(http.request, request_id)
            if err is not None:
                return err
            payload = payload or {}

            status = (payload.get("status") or "").strip().lower()
            if status not in ("success", "failed"):
                return fail(
                    message="status must be 'success' or 'failed'",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )

            order_id = payload.get("order_id")
            order_number = (payload.get("order_number") or "").strip()
            transaction_id = payload.get("transaction_id")

            if order_id is None and not order_number:
                return fail(
                    message="order_id or order_number is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )

            SaleOrder = env["sale.order"].sudo()
            order = None
            if order_id is not None:
                try:
                    order = SaleOrder.browse(int(order_id))
                except (TypeError, ValueError):
                    order = SaleOrder
            if order and order.exists():
                pass
            elif order_number:
                order = SaleOrder.search([("name", "=", order_number)], limit=1)
            else:
                order = SaleOrder

            if not order or not order.exists():
                _logger.warning(
                    "payment.qpay_callback order not found order_id=%s order_number=%s request_id=%s",
                    order_id,
                    order_number,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail(
                    message="Order not found",
                    code="NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )

            payment_method = getattr(order, "x_payment_method", None) or ""
            if status == "success":
                if order.state == "draft" and payment_method == "qpay_pending":
                    order.action_confirm()
                    _logger.info(
                        "payment.qpay_callback confirmed order id=%s name=%s transaction_id=%s request_id=%s",
                        order.id,
                        order.name,
                        transaction_id,
                        request_id,
                        extra={"request_id": request_id, "order_id": order.id},
                    )
                    return ok(
                        data={
                            "order_id": order.id,
                            "order_number": order.name,
                            "status": order.state,
                            "payment_status": "paid",
                        },
                        request_id=request_id,
                    )
                if order.state != "draft":
                    return ok(
                        data={
                            "order_id": order.id,
                            "order_number": order.name,
                            "status": order.state,
                            "message": "Order already confirmed",
                        },
                        request_id=request_id,
                    )
                return ok(
                    data={
                        "order_id": order.id,
                        "order_number": order.name,
                        "status": order.state,
                    },
                    request_id=request_id,
                )
            _logger.info(
                "payment.qpay_callback status=failed order_id=%s request_id=%s",
                order.id,
                request_id,
                extra={"request_id": request_id},
            )
            return ok(
                data={
                    "order_id": order.id,
                    "order_number": order.name,
                    "status": order.state,
                    "payment_status": "failed",
                },
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "payment.qpay_callback error: %s request_id=%s",
                e,
                request_id,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="ERROR",
                http_status=500,
                request_id=request_id,
            )
