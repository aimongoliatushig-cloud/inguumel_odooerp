# -*- coding: utf-8 -*-
"""
POS Online Orders: GET /api/v1/pos/online-orders – sale orders (mobile) scoped by warehouse for POS to display/process.
"""
import logging

from odoo import http

from odoo.addons.inguumel_mobile_api.controllers.base import get_request_id, ok, fail
from odoo.addons.inguumel_order_mxm.controllers.warehouse_scope import (
    get_warehouse_owner_warehouse_ids,
    is_warehouse_owner,
)

_logger = logging.getLogger(__name__)

LIST_LIMIT_MAX = 50
STATUS_LABELS_MN = {
    "received": "Захиалга авлаа",
    "preparing": "Бэлтгэж байна",
    "prepared": "Бэлтгэж дууссан",
    "out_for_delivery": "Хүргэлтэд гарсан",
    "delivered": "Хүргэгдсэн",
    "cancelled": "Цуцлагдсан",
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


def _user_can_cash_confirm(user):
    """True if user is allowed to confirm COD cash (cashier or administrator)."""
    try:
        return user.has_group("base.group_system") or user.has_group(
            "inguumel_order_mxm.group_cash_confirm"
        )
    except Exception:
        return False


def _order_to_pos_item(order, user=None):
    """One sale.order as POS online order item. Fields aligned with Delivery Workbench and contract.
    x_paid: single source of truth from sale.order.x_paid only (do not derive from payment_method/payment_state).
    can_cash_confirm = (COD + delivered + not x_paid) AND user has cashier permission.
    """
    partner = order.partner_id
    status_code = (
        getattr(order, "mxm_delivery_status", None)
        or getattr(order, "mxm_last_status_code", None)
        or "received"
    )
    phone_primary = (
        (getattr(order, "x_phone_primary", None) or (partner.phone or partner.mobile or "") if partner else "")
    ).strip()
    phone_secondary = (getattr(order, "x_phone_secondary", None) or "").strip()
    last_change = None
    if getattr(order, "mxm_last_status_at", None):
        last_change = order.mxm_last_status_at.strftime("%Y-%m-%d %H:%M:%S")
    elif getattr(order, "write_date", None):
        last_change = order.write_date.strftime("%Y-%m-%d %H:%M:%S")
    amount = getattr(order, "amount_total", 0) or 0
    # Single source of truth: only sale.order.x_paid (do NOT compute from payment_method or payment_state)
    x_paid = (order.x_paid is True)
    x_payment_method = getattr(order, "x_payment_method", None) or ""
    is_delivered = status_code == "delivered"
    can_cash_confirm = (
        x_payment_method == "cod"
        and is_delivered
        and (not x_paid)
        and (user is not None and _user_can_cash_confirm(user))
    )
    return {
        "order_id": order.id,
        "order_number": order.name,
        "warehouse_id": order.warehouse_id.id if order.warehouse_id else None,
        "partner_id": partner.id if partner else None,
        "customer_name": partner.name if partner else "",
        "partner_name": partner.name if partner else "",
        "phone_primary": phone_primary,
        "phone_secondary": phone_secondary or None,
        "phone": phone_primary,
        "delivery_address": (getattr(order, "x_delivery_address", None) or "").strip(),
        "total_amount": amount,
        "amount_total": amount,
        "state": order.state,
        "mxm_delivery_status": status_code,
        "delivery_status_code": status_code,
        "delivery_status_label_mn": STATUS_LABELS_MN.get(status_code, status_code),
        "last_change": last_change,
        "x_paid": x_paid,
        "x_payment_method": x_payment_method,
        "is_delivered": is_delivered,
        "can_cash_confirm": can_cash_confirm,
        "x_cash_confirmed_at": order.x_cash_confirmed_at.isoformat()
        if getattr(order, "x_cash_confirmed_at", None) and order.x_cash_confirmed_at
        else None,
        "x_cash_confirmed_by": order.x_cash_confirmed_by.id
        if getattr(order, "x_cash_confirmed_by", None) and order.x_cash_confirmed_by
        else None,
        "lines": [
            {
                "product_id": line.product_id.id,
                "product_name": line.product_id.display_name if line.product_id else "",
                "qty": line.product_uom_qty,
                "price_unit": line.price_unit,
            }
            for line in order.order_line
        ],
    }


class PosOnlineOrdersAPI(http.Controller):
    """POS: load online (mobile) orders by warehouse."""

    @http.route(
        "/api/v1/pos/online-orders",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def list_online_orders(self, config_id=None, warehouse_id=None, state="pending", limit=20, offset=0, **kwargs):
        """GET /api/v1/pos/online-orders – sale orders for POS (warehouse-scoped). state=pending => not delivered/cancelled."""
        request_id = get_request_id()
        try:
            _logger.info(
                "pos.online_orders list config_id=%s warehouse_id=%s state=%s request_id=%s",
                config_id,
                warehouse_id,
                state,
                request_id,
                extra={"request_id": request_id},
            )
            user, err = _require_user(request_id)
            if err is not None:
                return err
            env = http.request.env

            # Resolve warehouse: config_id (pos.config.warehouse_id) or warehouse_id param.
            # Fallback: if config_id given but pos.config has no warehouse_id, use company default
            # so Delivery POS still shows orders (mobile orders have sale.order.warehouse_id set).
            wh_id = None
            if config_id is not None and str(config_id).strip() != "":
                try:
                    cid = int(config_id)
                    PosConfig = env["pos.config"].sudo()
                    config = PosConfig.browse(cid)
                    if config.exists():
                        if getattr(config, "warehouse_id", None) and config.warehouse_id.exists():
                            wh_id = config.warehouse_id.id
                        else:
                            _logger.warning(
                                "pos.online_orders config_id=%s has no warehouse_id; will use param or fallback request_id=%s",
                                cid,
                                request_id,
                                extra={"request_id": request_id},
                            )
                except (TypeError, ValueError):
                    pass
            if wh_id is None and warehouse_id is not None and str(warehouse_id).strip() != "":
                try:
                    wh_id = int(warehouse_id)
                except (TypeError, ValueError):
                    pass
            if wh_id is None:
                # Fallback: first warehouse in user scope (warehouse owner) or company (stock user)
                wh_owner_ids = get_warehouse_owner_warehouse_ids(user)
                if wh_owner_ids:
                    wh_id = wh_owner_ids[0]
                    _logger.info(
                        "pos.online_orders using first warehouse from scope wh_id=%s request_id=%s",
                        wh_id,
                        request_id,
                        extra={"request_id": request_id},
                    )
                else:
                    Warehouse = env["stock.warehouse"].sudo()
                    first_wh = Warehouse.search(
                        [("company_id", "=", user.company_id.id)], limit=1, order="id"
                    )
                    if first_wh:
                        wh_id = first_wh.id
                        _logger.info(
                            "pos.online_orders using company default warehouse wh_id=%s request_id=%s",
                            wh_id,
                            request_id,
                            extra={"request_id": request_id},
                        )
            if wh_id is None:
                return fail(
                    message="warehouse_id or config_id with warehouse is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )

            # Scope: warehouse owner (x_warehouse_ids) or stock user for same-company warehouse (Delivery POS visibility)
            wh_owner_ids = get_warehouse_owner_warehouse_ids(user)
            if wh_owner_ids is not None:
                if wh_id not in wh_owner_ids:
                    return fail(
                        message="Warehouse not in your scope",
                        code="FORBIDDEN",
                        http_status=403,
                        request_id=request_id,
                    )
            else:
                # Not a warehouse owner: allow if stock user and warehouse belongs to user's company (Delivery POS)
                Warehouse = env["stock.warehouse"].sudo()
                wh = Warehouse.browse(wh_id)
                if not wh.exists():
                    return fail(
                        message="Warehouse not found",
                        code="VALIDATION_ERROR",
                        http_status=400,
                        request_id=request_id,
                    )
                if wh.company_id.id != user.company_id.id:
                    return fail(
                        message="Warehouse not in your company",
                        code="FORBIDDEN",
                        http_status=403,
                        request_id=request_id,
                    )
                if not user.has_group("stock.group_stock_user"):
                    return fail(
                        message="POS online orders require warehouse access or stock user",
                        code="FORBIDDEN",
                        http_status=403,
                        request_id=request_id,
                    )

            try:
                limit = min(int(limit), LIST_LIMIT_MAX) if limit else 20
            except (TypeError, ValueError):
                limit = 20
            try:
                offset = max(0, int(offset)) if offset else 0
            except (TypeError, ValueError):
                offset = 0

            SaleOrder = env["sale.order"].sudo()
            domain = [
                ("warehouse_id", "=", wh_id),
                ("state", "in", ["sale", "done"]),
            ]
            # pending = not (delivered|cancelled). Explicitly include unset (False/None) so newly confirmed mobile orders appear.
            # OR must be top-level tokens: extend with "|", (cond1), (cond2) — not append a list (else condition[1] is tuple → .lower() fails).
            if state == "pending":
                domain.extend([
                    "|",
                    ("mxm_delivery_status", "=", False),
                    ("mxm_delivery_status", "in", ["received", "preparing", "prepared", "out_for_delivery"]),
                ])
            elif state == "delivered":
                domain.append(("mxm_delivery_status", "=", "delivered"))
            elif state == "cancelled":
                domain.append(("mxm_delivery_status", "=", "cancelled"))

            _logger.info(
                "pos.online_orders domain=%s",
                domain,
                extra={"request_id": request_id},
            )
            orders = SaleOrder.search(
                domain,
                order="date_order desc, id desc",
                limit=limit,
                offset=offset,
            )
            items = [_order_to_pos_item(o, user) for o in orders]
            total = SaleOrder.search_count(domain)

            return ok(
                data=items,
                meta={"count": len(items), "total": total, "limit": limit, "offset": offset},
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "pos.online_orders error request_id=%s: %s",
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
