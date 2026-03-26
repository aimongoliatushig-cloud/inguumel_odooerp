# -*- coding: utf-8 -*-
"""
GET /api/v1/orders/<order_id>/delivery – delivery status + timeline (mobile read).
POST /api/v1/orders/<order_id>/delivery/status – set status (staff/admin or warehouse owner).
Driver can only set delivery status (e.g. delivered). Payment (x_paid) is never set here;
for COD, use POST /api/v1/orders/<id>/cash-confirm (cashier/manager only).
"""
import json
import logging
import traceback
from odoo import http
from odoo.addons.inguumel_mobile_api.controllers.base import (
    get_request_id,
    ok,
    fail,
    fail_payload,
)
from odoo.addons.inguumel_order_mxm.controllers.warehouse_scope import (
    order_in_warehouse_scope,
    is_warehouse_owner,
)
from odoo.addons.inguumel_order_mxm.models.sale_order import MXM_ALLOWED_TRANSITIONS

_logger = logging.getLogger(__name__)

# Terminal statuses: no next_actions expected; no blocked_reason.
MXM_TERMINAL_STATUSES = frozenset(("delivered", "cancelled"))

DELIVERY_API_DISABLED_KEY = "api_disabled:/api/v1/orders/delivery"

# Labels for API response (canonical codes)
DELIVERY_STATUS_LABELS = {
    "received": "Захиалга авлаа",
    "preparing": "Бэлтгэж байна",
    "prepared": "Бэлтгэж дууссан",
    "out_for_delivery": "Хүргэлтэд гарсан",
    "delivered": "Хүргэгдсэн",
    "cancelled": "Цуцлагдсан",
}

VALID_STATUS_CODES = frozenset(DELIVERY_STATUS_LABELS)


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


def _require_staff_or_admin_or_warehouse_owner(request_id):
    """Allow staff, admin, or warehouse owner (x_warehouse_ids). Warehouse owner needs order scope check at call site."""
    user, err = _require_user(request_id)
    if err is not None:
        return None, err
    has_stock = user.has_group("stock.group_stock_user")
    has_system = user.has_group("base.group_system")
    wh_owner = is_warehouse_owner(user)
    if has_stock or has_system or wh_owner:
        return user, None
    try:
        wh_ids = list(user.x_warehouse_ids.ids) if getattr(user, "x_warehouse_ids", None) and getattr(user.x_warehouse_ids, "ids", None) else []
    except Exception:
        wh_ids = []
    _logger.info(
        "delivery forbidden uid=%s partner_id=%s has_stock=%s has_system=%s is_warehouse_owner=%s warehouse_ids=%s request_id=%s",
        user.id,
        user.partner_id.id if user.partner_id else None,
        has_stock,
        has_system,
        wh_owner,
        wh_ids,
        request_id,
        extra={"request_id": request_id},
    )
    return None, fail_payload(
        message="Access denied. This app is only for warehouse and delivery staff.",
        code="FORBIDDEN",
        http_status=403,
        request_id=request_id,
    )


def _delivery_payload(order, request_id):
    """Build data dict: order_id, current_status, timeline, last_update_at, version,
    next_actions, optional blocked_reason, picking_id, picking_state (for Drive App / RN)."""
    try:
        order_id = order.id
        current = getattr(order, "mxm_delivery_status", None) or getattr(order, "mxm_last_status_code", None)
        logs = getattr(order, "mxm_status_log_ids", None) or []
        logs = logs.sorted("at asc") if logs else []
        last_log = logs[-1] if logs else None
        last_update_at = last_log.at.isoformat() if last_log and last_log.at else None
        # Monotonic version for efficient polling (client can send ?version=X and skip if unchanged)
        version = last_log.id if last_log else 0
        label = DELIVERY_STATUS_LABELS.get(current, current or "")
        at_str = last_log.at.isoformat() if last_log and last_log.at else None
        current_status = {
            "code": current,
            "label": label,
            "at": at_str,
        }
        timeline = []
        for log in logs:
            is_current = getattr(log, "is_last", None) if hasattr(log, "is_last") else (log == last_log)
            item = {
                "code": log.code,
                "label": DELIVERY_STATUS_LABELS.get(log.code, log.code or ""),
                "at": log.at.isoformat() if log.at else None,
                "is_current": bool(is_current),
                "note": log.note or None,
            }
            if getattr(log, "source", None):
                item["source"] = log.source
            timeline.append(item)

        # next_actions: allowed status codes from same rules as POST validation (read-only exposure)
        next_actions = list(MXM_ALLOWED_TRANSITIONS.get(current, []))

        # Picking info (same as POST: first outgoing picking)
        pickings = order._mxm_get_outgoing_pickings()
        first_picking = pickings[0] if pickings else None
        picking_id = first_picking.id if first_picking else None
        picking_state = first_picking.state if first_picking else None

        # Optional blocked_reason when no actions and not terminal and no picking (informational only)
        blocked_reason = None
        if not next_actions and current not in MXM_TERMINAL_STATUSES and not pickings:
            blocked_reason = "NO_DELIVERY_PICKING"

        payment_method = getattr(order, "x_payment_method", None) or ""
        cod_confirmed = bool(getattr(order, "x_cod_confirmed", False))
        cod_confirmed_at = order.x_cod_confirmed_at.isoformat() if getattr(order, "x_cod_confirmed_at", None) and order.x_cod_confirmed_at else None
        cod_amount = float(order.x_cod_amount) if getattr(order, "x_cod_amount", None) and order.x_cod_amount else None

        return {
            "order_id": order_id,
            "current_status": current_status,
            "timeline": timeline,
            "last_update_at": last_update_at,
            "version": version,
            "next_actions": next_actions,
            "blocked_reason": blocked_reason,
            "picking_id": picking_id,
            "picking_state": picking_state,
            "payment_method": payment_method,
            "cod_confirmed": cod_confirmed,
            "cod_confirmed_at": cod_confirmed_at,
            "cod_amount": cod_amount,
        }
    except Exception as e:
        _logger.exception(
            "delivery payload build error order_id=%s request_id=%s: %s",
            order.id,
            request_id,
            e,
            extra={"request_id": request_id},
        )
        raise


def _disabled_response(request_id):
    """Kill-switch: return 503 with code DISABLED, data null."""
    return fail_payload(
        message="delivery api disabled by config",
        code="DISABLED",
        http_status=503,
        data=None,
        request_id=request_id,
    )


class DeliveryAPI(http.Controller):
    """Delivery status and timeline: GET (read) and POST (staff set status)."""

    @http.route(
        "/api/v1/orders/<int:order_id>/delivery",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def get_delivery(self, order_id, **kwargs):
        """GET /api/v1/orders/<order_id>/delivery – return delivery status + timeline (owner only)."""
        request_id = get_request_id()
        try:
            _logger.info(
                "delivery.get order_id=%s request_id=%s",
                order_id,
                request_id,
                extra={"request_id": request_id},
            )
            ICP = http.request.env["ir.config_parameter"].sudo()
            if ICP.get_param(DELIVERY_API_DISABLED_KEY, "0").lower() in ("1", "true"):
                return _disabled_response(request_id)
            user, err = _require_user(request_id)
            if err is not None:
                return err
            env = http.request.env
            SaleOrder = env["sale.order"].sudo()
            order = SaleOrder.browse(order_id)
            if not order.exists():
                return fail_payload(
                    message="Order not found",
                    code="NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            if order_in_warehouse_scope(order, user):
                pass
            elif is_warehouse_owner(user):
                return fail_payload(
                    message="Forbidden",
                    code="FORBIDDEN",
                    http_status=403,
                    request_id=request_id,
                )
            elif order.partner_id.id != user.partner_id.id:
                return fail_payload(
                    message="Order not found",
                    code="NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            order.sudo()._mxm_ensure_initial_delivery_status()
            order.invalidate_recordset()
            data = _delivery_payload(order, request_id)
            return ok(data=data, request_id=request_id)
        except Exception as e:
            _logger.exception(
                "delivery.get error order_id=%s request_id=%s: %s\n%s",
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

    @http.route(
        "/api/v1/orders/<int:order_id>/delivery/status",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def post_delivery_status(self, order_id, **kwargs):
        """POST /api/v1/orders/<order_id>/delivery/status – set status (staff/admin only). Body: { status, note? }."""
        request_id = get_request_id()
        try:
            _logger.info(
                "delivery.post_status order_id=%s request_id=%s",
                order_id,
                request_id,
                extra={"request_id": request_id},
            )
            ICP = http.request.env["ir.config_parameter"].sudo()
            if ICP.get_param(DELIVERY_API_DISABLED_KEY, "0").lower() in ("1", "true"):
                return _disabled_response(request_id)
            user, err = _require_staff_or_admin_or_warehouse_owner(request_id)
            if err is not None:
                return err
            ct = (http.request.httprequest.content_type or "").strip().lower()
            raw = http.request.httprequest.get_data(as_text=True) or "{}"
            if "application/json" in ct:
                try:
                    body = json.loads(raw) if raw.strip() else {}
                except (TypeError, ValueError):
                    body = {}
            else:
                body = {}
            if not isinstance(body, dict):
                body = {}
            status = (body.get("status") or "").strip().lower()
            note = (body.get("note") or "").strip() or None
            if not status:
                return fail_payload(
                    message="status is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            if status not in VALID_STATUS_CODES:
                return fail_payload(
                    message="Invalid status code",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            env = http.request.env
            SaleOrder = env["sale.order"].sudo()
            order = SaleOrder.browse(order_id)
            if not order.exists():
                return fail_payload(
                    message="Order not found",
                    code="NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            if is_warehouse_owner(user):
                if not order_in_warehouse_scope(order, user):
                    try:
                        wh_ids = list(user.x_warehouse_ids.ids) if getattr(user, "x_warehouse_ids", None) else []
                    except Exception:
                        wh_ids = []
                    order_wh_id = order.warehouse_id.id if getattr(order, "warehouse_id", None) and order.warehouse_id else None
                    _logger.info(
                        "delivery.post_status 403 order_id=%s uid=%s order_warehouse_id=%s user_warehouse_ids=%s warehouse_scope denied request_id=%s",
                        order_id,
                        user.id,
                        order_wh_id,
                        wh_ids,
                        request_id,
                        extra={"request_id": request_id},
                    )
                    return fail_payload(
                        message="Forbidden",
                        code="FORBIDDEN",
                        http_status=403,
                        request_id=request_id,
                    )
                source = "mobile_owner"
                order_wh_id = order.warehouse_id.id if order.warehouse_id else None
                before = order.mxm_delivery_status or order.mxm_last_status_code
                _logger.info(
                    "delivery.post_status mobile_owner user_id=%s warehouse_id=%s order_id=%s before=%s after=%s source=mobile_owner request_id=%s",
                    user.id,
                    order_wh_id,
                    order_id,
                    before,
                    status,
                    request_id,
                    extra={"request_id": request_id},
                )
            else:
                source = "staff"
            ok_set, err_msg, error_code, stock_effect = order._mxm_set_status(
                status,
                note=note,
                source=source,
                user_id=user.id,
            )
            if not ok_set:
                http_status = 409 if error_code == "OUT_OF_STOCK" else 400
                return fail_payload(
                    message=err_msg or "Transition not allowed",
                    code=error_code or "VALIDATION_ERROR",
                    http_status=http_status,
                    request_id=request_id,
                )
            order.invalidate_recordset()
            data = _delivery_payload(order, request_id)
            pickings = order._mxm_get_outgoing_pickings()
            first_picking = pickings[0] if pickings else None
            data["picking_id"] = first_picking.id if first_picking else None
            data["picking_state"] = first_picking.state if first_picking else None
            data["stock_effect"] = stock_effect or "none"
            data["new_status"] = status
            return ok(data=data, request_id=request_id)
        except Exception as e:
            _logger.exception(
                "delivery.post_status error order_id=%s request_id=%s: %s\n%s",
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
