# -*- coding: utf-8 -*-
"""GET /api/v1/mxm/orders – list and detail for logged-in mobile user."""
import logging
from odoo import http
from odoo.addons.inguumel_mobile_api.controllers.base import get_request_id, ok, fail
from odoo.addons.inguumel_order_mxm.controllers.warehouse_scope import (
    get_warehouse_owner_warehouse_ids,
    is_warehouse_owner,
    order_in_warehouse_scope,
)

_logger = logging.getLogger(__name__)

LIST_LIMIT_MAX = 50
PRODUCT_IMAGE_SIZE = 512

# Canonical order state + Mongolian labels (backend canonical; see docs/order_lifecycle.md)
# draft/sent (quotation) -> PENDING_MERCHANT; sale -> CONFIRMED; done -> DELIVERED; cancel -> CANCELLED
ORDER_STATE_MAP = {
    "draft": ("PENDING_MERCHANT", "Хүлээгдэж байна"),
    "sent": ("PENDING_MERCHANT", "Хүлээгдэж байна"),
    "sale": ("CONFIRMED", "Баталгаажсан"),
    "done": ("DELIVERED", "Хүргэгдсэн"),
    "cancel": ("CANCELLED", "Цуцалсан"),
}
ORDER_STATE_DEFAULT = ("PENDING_MERCHANT", "Хүлээгдэж байна")

# Canonical payment method + Mongolian labels (COD / QPay / prepaid)
PAYMENT_METHOD_MAP = {
    "cod": ("COD", "Бэлнээр"),
    "qpay_pending": ("QPAY", "QPay"),
    "qpay_paid": ("QPAY_PAID", "QPay төлөгдсөн"),
    "card_paid": ("CARD_PAID", "Картаар төлөгдсөн"),
    "wallet_paid": ("WALLET_PAID", "Түрийвч төлөгдсөн"),
}
PAYMENT_METHOD_DEFAULT = ("OTHER", "Бусад")

# Canonical payment state: PAID / UNPAID (Mongolian labels)
PAYMENT_STATE_PAID = ("PAID", "Төлөгдсөн")
PAYMENT_STATE_UNPAID = ("UNPAID", "Төлөгдөөгүй")

# Status timeline codes + Mongolian labels (canonical lowercase)
STATUS_LOG_LABELS = {
    "received": "Захиалга авлаа",
    "preparing": "Бэлтгэж байна",
    "prepared": "Бэлтгэж дууссан",
    "out_for_delivery": "Хүргэлтэд гарсан",
    "delivered": "Хүргэгдсэн",
    "cancelled": "Цуцлагдсан",
    "cod_confirmed": "COD баталгаажсан",
}
# Fallback: Odoo state -> single status code (for old orders with no logs)
STATE_TO_STATUS_CODE = {
    "draft": "received",
    "sent": "received",
    "sale": "preparing",
    "done": "delivered",
    "cancel": "cancelled",
}


def _order_status_history(order):
    """
    Return status_history array for API: [{code, label, at}, ...] sorted asc by at.
    If order has mxm_status_log_ids, use them; else fallback from order.state (one item, not written to DB).
    """
    logs = getattr(order, "mxm_status_log_ids", None)
    if logs and len(logs) > 0:
        history = []
        for log in logs.sorted(key=lambda r: (r.at, r.id)):
            label = STATUS_LOG_LABELS.get(log.code, log.code)
            at_str = log.at.strftime("%Y-%m-%d %H:%M:%S") if log.at else ""
            history.append({"code": log.code, "label": label, "at": at_str})
        return history
    # Fallback for old orders: single item from state, do NOT write to DB
    code = STATE_TO_STATUS_CODE.get(order.state, "RECEIVED")
    label = STATUS_LOG_LABELS.get(code, code)
    at_dt = order.create_date or order.write_date
    at_str = at_dt.strftime("%Y-%m-%d %H:%M:%S") if at_dt else ""
    return [{"code": code, "label": label, "at": at_str}]


def _order_state_canonical(state):
    """Return (order_state, order_state_label_mn) from Odoo order.state."""
    if not state:
        return ORDER_STATE_DEFAULT
    entry = ORDER_STATE_MAP.get(state, ORDER_STATE_DEFAULT)
    return entry


def _payment_canonical(payment_method_raw, paid=False):
    """Return (payment_method_code, payment_method_label_mn, payment_state_code, payment_state_label_mn)."""
    method_key = (payment_method_raw or "cod").strip().lower()
    method_entry = PAYMENT_METHOD_MAP.get(method_key, PAYMENT_METHOD_DEFAULT)
    payment_method_code, payment_method_label_mn = method_entry
    if paid:
        payment_state_code, payment_state_label_mn = PAYMENT_STATE_PAID
    else:
        payment_state_code, payment_state_label_mn = PAYMENT_STATE_UNPAID
    return payment_method_code, payment_method_label_mn, payment_state_code, payment_state_label_mn


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


def _format_partner_address(partner):
    """Build fallback address text from partner fields (street, city, state, zip, country)."""
    if not partner:
        return ""
    parts = []
    if getattr(partner, "street", None) and partner.street:
        parts.append(partner.street)
    if getattr(partner, "street2", None) and partner.street2:
        parts.append(partner.street2)
    city = getattr(partner, "city", None) and partner.city
    state = getattr(partner, "state_id", None) and partner.state_id.name
    zip_code = getattr(partner, "zip", None) and partner.zip
    country = getattr(partner, "country_id", None) and partner.country_id.name
    if city:
        parts.append(city)
    if state:
        parts.append(state)
    if zip_code:
        parts.append(zip_code)
    if country:
        parts.append(country)
    return ", ".join(parts) if parts else ""


def _order_line_to_item(line, base_url=""):
    """Build API item for one sale.order.line. Uses Odoo computed fields."""
    product = line.product_id
    product_id = product.id if product else None
    uom = getattr(line, "product_uom", None) or getattr(line, "product_uom_id", None)
    uom_name = uom.name if uom and uom.exists() else ""
    discount = getattr(line, "discount", None)
    if discount is None:
        discount = 0
    price_tax = getattr(line, "price_tax", None)
    write_date = getattr(product, "write_date", None)
    v = write_date.isoformat() if write_date else str(product_id or line.id)
    image_url = "%s/api/v1/mxm/product-image/%s?size=%s&v=%s" % (
        base_url.rstrip("/"),
        product_id or 0,
        PRODUCT_IMAGE_SIZE,
        v,
    )
    return {
        "id": line.id,
        "product_id": product_id,
        "product_name": product.display_name if product else "",
        "qty": line.product_uom_qty,
        "uom": uom_name,
        "price_unit": line.price_unit,
        "discount": discount,
        "subtotal": getattr(line, "price_subtotal", line.price_unit * line.product_uom_qty),
        "tax_amount": price_tax,
        "image_url": image_url,
    }


def _order_to_detail(order, base_url=""):
    """
    Build full order detail payload. Canonical: warehouse from sale.order.warehouse_id,
    shipping address from sale.order.x_delivery_address with fallback to partner.
    """
    partner = order.partner_id
    # Warehouse: MUST be from sale.order.warehouse_id (never from picking)
    warehouse = getattr(order, "warehouse_id", None)
    warehouse_id = warehouse.id if warehouse and warehouse.exists() else None
    warehouse_name = warehouse.display_name or (warehouse.name if warehouse else "") if warehouse and warehouse.exists() else ""

    # Amounts: use Odoo computed fields, do not recompute. Always expose (Drive app contract).
    amount_total = getattr(order, "amount_total", None)
    if amount_total is None:
        amount_total = 0.0
    amount_untaxed = getattr(order, "amount_untaxed", None)
    if amount_untaxed is None:
        amount_untaxed = 0.0
    amount_tax = getattr(order, "amount_tax", None)
    if amount_tax is None:
        amount_tax = 0.0

    # Shipping: canonical per-order is x_delivery_address; fallback to partner
    x_delivery = (getattr(order, "x_delivery_address", None) or "").strip()
    address_text = x_delivery if x_delivery else _format_partner_address(partner)
    x_phone_primary = (getattr(order, "x_phone_primary", None) or "").strip()
    x_phone_secondary = getattr(order, "x_phone_secondary", None)
    if x_phone_secondary is not None:
        x_phone_secondary = (x_phone_secondary or "").strip() or None
    phone_primary = x_phone_primary or (partner.phone or partner.mobile or "") if partner else ""
    phone_secondary = x_phone_secondary
    if phone_secondary is None and partner and getattr(partner, "x_phone_2", None):
        phone_secondary = (partner.x_phone_2 or "").strip() or None

    # Payment: canonical codes + Mongolian labels; is_paid from order or prepaid method
    payment_method_raw = getattr(order, "x_payment_method", None) or "cod"
    paid = getattr(order, "x_is_paid", None) in (True, "true", "1", 1) if hasattr(order, "x_is_paid") else False
    paid = paid or payment_method_raw in ("qpay_paid", "card_paid", "wallet_paid")
    # COD: driver confirm (x_cod_confirmed) -> PAID for list/detail contract consistency with delivery cod_confirmed
    if payment_method_raw == "cod" and getattr(order, "x_cod_confirmed", False):
        paid = True
    payment_status_raw = ("paid" if paid else "cod_pending") if payment_method_raw == "cod" else ("paid" if paid else "unpaid")
    order_state_code, order_state_label_mn = _order_state_canonical(order.state)
    (
        payment_method_code,
        payment_method_label_mn,
        payment_state_code,
        payment_state_label_mn,
    ) = _payment_canonical(payment_method_raw, paid=paid)

    # Lines: always present (array, possibly empty) – Drive app contract
    lines = []
    for line in order.order_line:
        lines.append(_order_line_to_item(line, base_url))

    # Status timeline (from mxm.order.status.log or fallback from state)
    status_history = _order_status_history(order)
    delivery_status_code, delivery_status_label_mn = _delivery_status_for_order(order)

    api_status = "confirmed" if order.state == "sale" else "processing"
    # Contract: all keys always present; order_line alias for older clients
    return {
        "id": order.id,
        "order_number": order.name,
        "date_order": order.date_order.isoformat() if order.date_order else None,
        "status": api_status,
        "state": order.state,
        # Stable contract (RN): order_state_code + order_state_label_mn
        "order_state_code": order_state_code,
        "order_state_label_mn": order_state_label_mn,
        "order_state": order_state_code,
        # Delivery status (same as list for filtering)
        "delivery_status_code": delivery_status_code,
        "delivery_status_label_mn": delivery_status_label_mn,
        "is_delivered": delivery_status_code == "delivered",
        "is_cancelled": delivery_status_code == "cancelled",
        # Stable contract: payment_method_code, payment_state_code, is_paid
        "payment_method_code": payment_method_code,
        "payment_method_label_mn": payment_method_label_mn,
        "payment_state_code": payment_state_code,
        "payment_state_label_mn": payment_state_label_mn,
        "is_paid": paid,
        # Status timeline (real timestamps; fallback for old orders)
        "status_history": status_history,
        # Backward compatibility
        "payment_method": payment_method_code,
        "payment_status": payment_state_code,
        "payment_status_label_mn": payment_state_label_mn,
        "currency": "MNT",
        "amount_total": amount_total,
        "warehouse": {
            "id": warehouse_id,
            "name": warehouse_name,
        },
        "amounts": {
            "total": amount_total,
            "untaxed": amount_untaxed,
            "tax": amount_tax,
        },
        "partner": {
            "id": partner.id if partner else None,
            "name": partner.name if partner else "",
            "phone": (partner.phone or partner.mobile or "") if partner else "",
        },
        "shipping": {
            "address_text": address_text,
            "phone_primary": phone_primary,
            "phone_secondary": phone_secondary,
        },
        "payment": {
            "payment_method": payment_method_raw,
            "payment_status": payment_status_raw,
            "paid": paid,
        },
        "lines": lines,
        "order_line": lines,  # Alias for older clients; same reference as lines
    }


def _delivery_status_for_order(order):
    """
    Return (delivery_status_code, delivery_status_label_mn) for list/detail.
    Canonical: mxm_delivery_status or mxm_last_status_code, else fallback from state.
    """
    code = (
        getattr(order, "mxm_delivery_status", None)
        or getattr(order, "mxm_last_status_code", None)
        or STATE_TO_STATUS_CODE.get(order.state, "received")
    )
    label = STATUS_LOG_LABELS.get(code, code)
    return code, label


def _order_to_item(order):
    """Build API item dict for one sale.order. Stable field names; backward compat kept."""
    warehouse = getattr(order, "warehouse_id", None)
    warehouse_id = warehouse.id if warehouse and warehouse.exists() else None
    payment_method_raw = getattr(order, "x_payment_method", None) or "cod"
    paid = getattr(order, "x_is_paid", None) in (True, "true", "1", 1) if hasattr(order, "x_is_paid") else False
    paid = paid or payment_method_raw in ("qpay_paid", "card_paid", "wallet_paid")
    # COD: driver confirm (x_cod_confirmed) -> PAID for list/detail contract consistency
    if payment_method_raw == "cod" and getattr(order, "x_cod_confirmed", False):
        paid = True
    payment_status_raw = ("paid" if paid else "cod_pending") if payment_method_raw == "cod" else ("paid" if paid else "unpaid")
    api_status = "confirmed" if order.state == "sale" else "processing"
    order_state_code, order_state_label_mn = _order_state_canonical(order.state)
    (
        payment_method_code,
        payment_method_label_mn,
        payment_state_code,
        payment_state_label_mn,
    ) = _payment_canonical(payment_method_raw, paid=paid)
    delivery_status_code, delivery_status_label_mn = _delivery_status_for_order(order)
    is_delivered = delivery_status_code == "delivered"
    is_cancelled = delivery_status_code == "cancelled"
    return {
        "order_id": order.id,
        "order_number": order.name,
        "warehouse_id": warehouse_id,
        "status": api_status,
        "state": order.state,
        "order_state_code": order_state_code,
        "order_state_label_mn": order_state_label_mn,
        "payment_method_code": payment_method_code,
        "payment_method_label_mn": payment_method_label_mn,
        "payment_state_code": payment_state_code,
        "payment_state_label_mn": payment_state_label_mn,
        "is_paid": paid,
        # Delivery status for mobile filtering (no N+1)
        "delivery_status_code": delivery_status_code,
        "delivery_status_label_mn": delivery_status_label_mn,
        "is_delivered": is_delivered,
        "is_cancelled": is_cancelled,
        # Backward compatibility
        "order_state": order_state_code,
        "payment_method": payment_method_code,
        "payment_status": payment_state_code,
        "payment_status_label_mn": payment_state_label_mn,
        "paid": paid,
        "partner_id": order.partner_id.id,
        "amount_total": order.amount_total,
        "date_order": str(order.date_order) if order.date_order else None,
    }


class OrderListAPI(http.Controller):
    """My Orders – GET /api/v1/mxm/orders."""

    @http.route(
        "/api/v1/mxm/orders",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def list_orders(self, warehouse_id=None, limit=20, offset=0, wrap=None, **kwargs):
        """GET /api/v1/mxm/orders – list sale orders (customer: own orders; warehouse owner: orders in assigned warehouses)."""
        request_id = get_request_id()
        try:
            user, err = _require_user(request_id)
            if err is not None:
                return err
            env = http.request.env
            uid = env.uid
            warehouse_id_query = warehouse_id

            try:
                limit = min(int(limit), LIST_LIMIT_MAX) if limit else 20
            except (TypeError, ValueError):
                limit = 20
            try:
                offset = max(0, int(offset)) if offset else 0
            except (TypeError, ValueError):
                offset = 0

            # Warehouse owner: filter by warehouse_id IN user's x_warehouse_ids. Never use client warehouse_id to expand.
            wh_owner_ids = get_warehouse_owner_warehouse_ids(user)
            if wh_owner_ids is not None:
                domain = [("warehouse_id", "in", wh_owner_ids)]
                if warehouse_id is not None and warehouse_id != "":
                    try:
                        wh_int = int(warehouse_id)
                        if wh_int in wh_owner_ids:
                            domain = [("warehouse_id", "=", wh_int)]
                    except (TypeError, ValueError):
                        pass
                partner_id = user.partner_id.id
            else:
                domain = [("partner_id", "=", user.partner_id.id)]
                if warehouse_id is not None and warehouse_id != "":
                    try:
                        domain.append(("warehouse_id", "=", int(warehouse_id)))
                    except (TypeError, ValueError):
                        pass
                partner_id = user.partner_id.id

            SaleOrder = env["sale.order"].sudo()
            orders = SaleOrder.search(
                domain,
                order="date_order desc, id desc",
                limit=limit,
                offset=offset,
            )
            items = [_order_to_item(o) for o in orders]
            total = SaleOrder.search_count(domain)
            result_count = len(items)

            _logger.info(
                "order.list request_id=%s uid=%s partner_id=%s warehouse_id_query=%s domain=%s result_count=%s total=%s",
                request_id,
                uid,
                partner_id,
                warehouse_id_query,
                domain,
                result_count,
                total,
                extra={
                    "request_id": request_id,
                    "uid": uid,
                    "partner_id": partner_id,
                    "warehouse_id_query": warehouse_id_query,
                    "domain": domain,
                    "result_count": result_count,
                    "total": total,
                },
            )

            meta = {"count": result_count, "total": total, "limit": limit, "offset": offset}
            if wrap in ("1", "true", "True", "items"):
                return ok(
                    data={"items": items, "meta": meta},
                    request_id=request_id,
                )
            return ok(
                data=items,
                meta=meta,
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "order.list error: %s request_id=%s",
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

    @http.route(
        "/api/v1/mxm/orders/<int:order_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def get_order(self, order_id, **kwargs):
        """GET /api/v1/mxm/orders/<order_id> – order detail for logged-in user (owner only)."""
        request_id = get_request_id()
        try:
            user, err = _require_user(request_id)
            if err is not None:
                return err
            env = http.request.env
            SaleOrder = env["sale.order"].sudo()
            order = SaleOrder.browse(order_id)
            if not order.exists():
                _logger.info(
                    "order.detail not found order_id=%s request_id=%s",
                    order_id,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail(
                    message="Order not found",
                    code="NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            if order_in_warehouse_scope(order, user):
                pass
            elif is_warehouse_owner(user):
                _logger.info(
                    "order.detail 403 order_id=%s uid=%s warehouse_scope denied request_id=%s",
                    order_id,
                    user.id,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail(
                    message="Forbidden",
                    code="FORBIDDEN",
                    http_status=403,
                    request_id=request_id,
                )
            elif order.partner_id.id != user.partner_id.id:
                _logger.info(
                    "order.detail forbidden order_id=%s partner_id=%s user_partner_id=%s request_id=%s",
                    order_id,
                    order.partner_id.id,
                    user.partner_id.id,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail(
                    message="Order not found",
                    code="NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            base_url = (http.request.httprequest.url_root or "").rstrip("/")
            data = _order_to_detail(order, base_url)
            _logger.info(
                "order.detail order_id=%s uid=%s request_id=%s",
                order_id,
                env.uid,
                request_id,
                extra={"request_id": request_id, "order_id": order_id},
            )
            return ok(data=data, request_id=request_id)
        except Exception as e:
            _logger.exception(
                "order.detail error: %s order_id=%s request_id=%s",
                e,
                order_id,
                request_id,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="ERROR",
                http_status=500,
                request_id=request_id,
            )
