# -*- coding: utf-8 -*-
"""
POST /api/v1/orders/<order_id>/cash-confirm – Cashier confirms COD cash received.
Only users with Cash Confirm (cashier) or Administrator can call this.
Driver cannot set paid; only this endpoint sets x_paid for COD (cashier flow).
"""
import logging
import traceback

from odoo import http
from odoo.addons.inguumel_mobile_api.controllers.base import (
    get_request_id,
    ok,
    fail_payload,
)
from odoo.addons.inguumel_order_mxm.controllers.warehouse_scope import (
    order_in_warehouse_scope,
    get_warehouse_owner_warehouse_ids,
)

_logger = logging.getLogger(__name__)

CASH_CONFIRM_API_DISABLED_KEY = "api_disabled:/api/v1/orders/cash-confirm"


def _require_user(request_id):
    user = http.request.env.user
    if not user or user._is_public():
        return None, fail_payload(
            message="Unauthorized",
            code="UNAUTHORIZED",
            http_status=401,
            request_id=request_id,
        )
    return user, None


def _require_cashier_or_admin(request_id):
    """Only cashier (group_cash_confirm) or administrator can confirm COD cash."""
    user, err = _require_user(request_id)
    if err is not None:
        return None, err
    try:
        if user.has_group("base.group_system"):
            return user, None
        if user.has_group("inguumel_order_mxm.group_cash_confirm"):
            return user, None
    except Exception:
        pass
    return None, fail_payload(
        message="Only cashier or manager can confirm cash.",
        code="FORBIDDEN",
        http_status=403,
        request_id=request_id,
    )


def _is_order_delivered(order):
    """True if order is considered delivered for cash confirm."""
    if getattr(order, "mxm_delivery_status", None) == "delivered":
        return True
    pickings = getattr(order, "picking_ids", None) or []
    outgoing = [
        p
        for p in pickings
        if p.picking_type_id and getattr(p.picking_type_id, "code", None) == "outgoing"
    ]
    if outgoing and all(p.state == "done" for p in outgoing):
        return True
    return False


class CashConfirmAPI(http.Controller):
    """Cash Confirm: cashier/manager marks COD order as paid."""

    @http.route(
        "/api/v1/orders/<int:order_id>/cash-confirm",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def post_cash_confirm(self, order_id, **kwargs):
        """
        POST /api/v1/orders/<order_id>/cash-confirm
        Body: {} or { "note": "optional" }.
        Requires: COD order, delivered, not yet paid. Caller must be cashier or admin.
        On success: x_paid=True, x_cash_confirmed_by, x_cash_confirmed_at set; Lucky Wheel recomputed.
        """
        request_id = get_request_id()
        try:
            _logger.info(
                "cash_confirm.post order_id=%s request_id=%s",
                order_id,
                request_id,
                extra={"request_id": request_id},
            )
            env = http.request.env
            try:
                ICP = env["ir.config_parameter"].sudo()
                if ICP.get_param(CASH_CONFIRM_API_DISABLED_KEY, "0").lower() in (
                    "1",
                    "true",
                ):
                    return fail_payload(
                        message="Cash confirm API is disabled",
                        code="SERVICE_UNAVAILABLE",
                        http_status=503,
                        request_id=request_id,
                    )
            except Exception:
                pass

            user, err = _require_cashier_or_admin(request_id)
            if err is not None:
                return err

            SaleOrder = env["sale.order"].sudo()
            order = SaleOrder.browse(order_id)
            if not order.exists():
                return fail_payload(
                    message="Order not found",
                    code="NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )

            # Warehouse scope: if user has warehouse scope, order must be in it
            wh_ids = get_warehouse_owner_warehouse_ids(user)
            if wh_ids and not order_in_warehouse_scope(order, user):
                return fail_payload(
                    message="Order is not in your warehouse scope",
                    code="FORBIDDEN",
                    http_status=403,
                    request_id=request_id,
                )

            payment_method = getattr(order, "x_payment_method", None) or ""
            if payment_method != "cod":
                return fail_payload(
                    message="Order is not COD; cash confirm only applies to COD orders",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )

            if order.state not in ("sale", "done"):
                return fail_payload(
                    message="Order must be confirmed (sale/done)",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )

            # Idempotency key: x_cash_confirmed_at only. Do NOT treat x_paid=True alone as already confirmed.
            if getattr(order, "x_cash_confirmed_at", None) and order.x_cash_confirmed_at:
                data = {
                    "order_id": order.id,
                    "order_number": order.name,
                    "x_paid": True,
                    "already_confirmed": True,
                    "x_cash_confirmed_by": order.x_cash_confirmed_by.id
                    if getattr(order, "x_cash_confirmed_by", None) and order.x_cash_confirmed_by
                    else None,
                    "x_cash_confirmed_at": order.x_cash_confirmed_at.isoformat(),
                }
                return ok(data=data, message="Already confirmed", request_id=request_id)

            if not _is_order_delivered(order):
                return fail_payload(
                    message="Order must be delivered before cash can be confirmed",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )

            order.action_cash_confirm()
            order.invalidate_recordset()

            data = {
                "order_id": order.id,
                "order_number": order.name,
                "x_paid": True,
                "already_confirmed": False,
                "x_cash_confirmed_by": user.id,
                "x_cash_confirmed_at": order.x_cash_confirmed_at.isoformat()
                if order.x_cash_confirmed_at
                else None,
            }
            return ok(data=data, message="Cash confirmed", request_id=request_id)

        except Exception as e:
            _logger.exception(
                "cash_confirm.post error order_id=%s request_id=%s: %s\n%s",
                order_id,
                request_id,
                e,
                traceback.format_exc(),
                extra={"request_id": request_id},
            )
            return fail_payload(
                message="Internal error",
                code="ERROR",
                http_status=500,
                request_id=request_id,
            )
