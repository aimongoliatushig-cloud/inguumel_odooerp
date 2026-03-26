# -*- coding: utf-8 -*-
"""
Drive App API: login (res.users only), auth/me, warehouse-scoped orders and delivery.

- POST /api/v1/driver/auth/login – JSON { login, password }; only res.users with x_warehouse_ids.
- GET  /api/v1/driver/auth/me – Bearer; uid, partner_id, role, warehouse_ids.
- GET  /api/v1/driver/orders – list orders for user's warehouses (403 if not warehouse_owner or no warehouses).
- GET  /api/v1/driver/orders/<id> – order detail (403 if other warehouse).
- GET  /api/v1/driver/orders/<id>/delivery – delivery status (same scope).
- POST /api/v1/driver/orders/<id>/delivery/status – set status (same scope).
"""
import json
import logging
import traceback

from odoo import http
from odoo.exceptions import UserError, ValidationError
from odoo.addons.inguumel_mobile_api.controllers.base import (
    get_request_id,
    ok,
    fail_payload,
)
from odoo.addons.inguumel_mobile_api.controllers.auth import (
    _auth_login_phone_pin,
    _enrich_login_data,
    _mxm_role_for_user,
)
from odoo.addons.inguumel_order_mxm.controllers.warehouse_scope import (
    get_warehouse_owner_warehouse_ids,
    is_warehouse_owner,
    order_in_warehouse_scope,
)
from odoo.addons.inguumel_order_mxm.controllers.order_list import (
    LIST_LIMIT_MAX,
    _order_to_detail,
    _order_to_item,
)
from odoo.addons.inguumel_order_mxm.controllers.delivery import (
    VALID_STATUS_CODES,
    _delivery_payload,
)

_logger = logging.getLogger(__name__)

DRIVER_API_DISABLED_KEY = "api_disabled:/api/v1/driver"
COD_CONFIRM_ALLOWED_STATUSES = frozenset(("received", "preparing", "prepared", "out_for_delivery", "delivered"))


def _driver_disabled_response(request_id):
    """Kill-switch: 503 with code DISABLED."""
    return fail_payload(
        message="Driver API disabled by config",
        code="DISABLED",
        http_status=503,
        data=None,
        request_id=request_id,
    )


def _parse_json_body(request, request_id):
    """Parse JSON body; return (data_dict, error_response)."""
    if hasattr(request, "jsonrequest") and request.jsonrequest is not None:
        data = request.jsonrequest if isinstance(request.jsonrequest, dict) else {}
        return data, None
    ct = (request.httprequest.content_type or "").strip().lower()
    if "application/json" not in ct:
        return None, fail_payload(
            message="Invalid JSON",
            code="VALIDATION_ERROR",
            http_status=400,
            request_id=request_id,
        )
    raw = request.httprequest.get_data(as_text=True)
    if not raw or not raw.strip():
        return None, fail_payload(
            message="Invalid JSON",
            code="VALIDATION_ERROR",
            http_status=400,
            request_id=request_id,
        )
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None, fail_payload(
            message="Invalid JSON",
            code="VALIDATION_ERROR",
            http_status=400,
            request_id=request_id,
        )
    if not isinstance(data, dict):
        return None, fail_payload(
            message="Invalid JSON",
            code="VALIDATION_ERROR",
            http_status=400,
            request_id=request_id,
        )
    return data, None


def _create_driver_token(env, uid, request_id):
    """Create Bearer token for driver. Returns token string or None."""
    try:
        token = env["api.access.token"].sudo().create_token(uid)
    except Exception as e:
        _logger.exception(
            "driver _create_driver_token failed uid=%s request_id=%s: %s",
            uid,
            request_id,
            e,
            extra={"request_id": request_id},
        )
        return None
    if not token or not isinstance(token, str) or not token.strip():
        _logger.error(
            "driver _create_driver_token empty uid=%s request_id=%s",
            uid,
            request_id,
            extra={"request_id": request_id},
        )
        return None
    return token.strip()


def _is_driver_allowed(user):
    """
    True if user is allowed as driver: res.users with non-empty x_warehouse_ids.
    """
    try:
        if not user:
            return False
        if getattr(user, "_is_public", lambda: False)():
            return False
        wh_ids = getattr(user, "x_warehouse_ids", None)
        if not wh_ids or not getattr(wh_ids, "ids", None):
            return False
        return bool(wh_ids.ids)
    except Exception:
        return False


def _require_user(request_id):
    """Return (user, None) or (None, error_response)."""
    user = http.request.env.user
    if not user or user._is_public():
        return None, fail_payload(
            message="Unauthorized",
            code="UNAUTHORIZED",
            http_status=401,
            request_id=request_id,
        )
    return user, None


def _require_driver(request_id):
    """
    Require authenticated warehouse owner with non-empty x_warehouse_ids.
    Return (user, warehouse_ids, None) or (None, None, error_response).
    - 401 if not authenticated.
    - 403 FORBIDDEN if not warehouse owner (role != warehouse_owner).
    - 403 WAREHOUSE_NOT_ASSIGNED if warehouse_ids empty.
    """
    user, err = _require_user(request_id)
    if err is not None:
        return None, None, err
    if not is_warehouse_owner(user):
        _logger.info(
            "driver scope denied: not warehouse owner uid=%s request_id=%s",
            user.id,
            request_id,
            extra={"request_id": request_id},
        )
        return None, None, fail_payload(
            message="Forbidden",
            code="FORBIDDEN",
            http_status=403,
            request_id=request_id,
        )
    wh_ids = get_warehouse_owner_warehouse_ids(user)
    if not wh_ids:
        _logger.info(
            "driver scope denied: warehouse_ids empty uid=%s request_id=%s",
            user.id,
            request_id,
            extra={"request_id": request_id},
        )
        return None, None, fail_payload(
            message="No warehouse assigned",
            code="WAREHOUSE_NOT_ASSIGNED",
            http_status=403,
            request_id=request_id,
        )
    return user, wh_ids, None


class DriverAuthAPI(http.Controller):
    """Drive App auth: login (res.users + warehouse), me."""

    @http.route(
        "/api/v1/driver/auth/login",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def login(self, **kwargs):
        """
        POST /api/v1/driver/auth/login – JSON { login, password }.
        Only res.users; must have x_warehouse_ids non-empty (403 WAREHOUSE_NOT_ASSIGNED if empty).
        """
        request_id = get_request_id()
        try:
            _logger.info(
                "driver.auth.login called request_id=%s",
                request_id,
                extra={"request_id": request_id},
            )
            ICP = http.request.env["ir.config_parameter"].sudo()
            if ICP.get_param(DRIVER_API_DISABLED_KEY, "0").lower() in ("1", "true"):
                return _driver_disabled_response(request_id)

            payload, err = _parse_json_body(http.request, request_id)
            if err is not None:
                return err
            payload = payload or {}

            # Compatibility: same contract as POST /api/v1/auth/login (phone + pin) → identical JSON + primary_role, roles, capabilities
            if payload.get("phone") is not None and payload.get("pin") is not None:
                data, err = _auth_login_phone_pin(payload, request_id)
                if err is not None:
                    return err
                env = http.request.env
                _enrich_login_data(env, data, request=http.request, app_hint="driver")
                caps = data.get("capabilities") or {}
                warehouse_ids = data.get("warehouse_ids") or []
                if not caps.get("can_driver_update_delivery_status"):
                    _logger.info(
                        "driver.auth.login 403 no driver capability uid=%s request_id=%s",
                        data.get("uid"),
                        request_id,
                        extra={"request_id": request_id},
                    )
                    return fail_payload(
                        message="Driver login is for users with driver capability only",
                        code="FORBIDDEN",
                        http_status=403,
                        request_id=request_id,
                    )
                if not warehouse_ids:
                    _logger.info(
                        "driver.auth.login 403 no warehouse assigned uid=%s request_id=%s",
                        data.get("uid"),
                        request_id,
                        extra={"request_id": request_id},
                    )
                    return fail_payload(
                        message="No warehouse assigned",
                        code="WAREHOUSE_NOT_ASSIGNED",
                        http_status=403,
                        request_id=request_id,
                    )
                return ok(data=data, request_id=request_id)

            login_str = (payload.get("login") or "").strip() if isinstance(payload.get("login"), str) else ""
            password_str = (payload.get("password") or "")
            if isinstance(password_str, str):
                password_str = password_str.strip()
            else:
                password_str = str(password_str).strip()

            if not login_str:
                return fail_payload(
                    message="login is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            if not password_str:
                return fail_payload(
                    message="password is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )

            env = http.request.env
            credential = {"login": login_str, "password": password_str, "type": "password"}
            try:
                auth_info = http.request.session.authenticate(env, credential)
                if not auth_info or not auth_info.get("uid"):
                    _logger.info(
                        "driver.auth.login invalid credentials request_id=%s",
                        request_id,
                        extra={"request_id": request_id},
                    )
                    return fail_payload(
                        message="Invalid credentials",
                        code="UNAUTHORIZED",
                        http_status=401,
                        request_id=request_id,
                    )
            except Exception as auth_err:
                _logger.info(
                    "driver.auth.login authenticate failed request_id=%s err=%s",
                    request_id,
                    auth_err,
                    extra={"request_id": request_id},
                )
                return fail_payload(
                    message="Invalid credentials",
                    code="UNAUTHORIZED",
                    http_status=401,
                    request_id=request_id,
                )

            uid = auth_info["uid"]
            user = env["res.users"].sudo().browse(uid)
            if not user.exists():
                return fail_payload(
                    message="Unauthorized",
                    code="UNAUTHORIZED",
                    http_status=401,
                    request_id=request_id,
                )

            # Drive App: only allow if x_warehouse_ids non-empty (must be warehouse owner with assignment)
            if not _is_driver_allowed(user):
                _logger.info(
                    "driver.auth.login 403 WAREHOUSE_NOT_ASSIGNED uid=%s request_id=%s",
                    uid,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail_payload(
                    message="No warehouse assigned",
                    code="WAREHOUSE_NOT_ASSIGNED",
                    http_status=403,
                    request_id=request_id,
                )

            access_token = _create_driver_token(env, uid, request_id)
            if access_token is None:
                _logger.error(
                    "driver.auth.login token creation failed uid=%s request_id=%s",
                    uid,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail_payload(
                    message="Internal error",
                    code="INTERNAL_ERROR",
                    http_status=500,
                    request_id=request_id,
                )

            warehouse_ids = list(user.x_warehouse_ids.ids)
            _logger.info(
                "driver.auth.login success uid=%s partner_id=%s warehouse_count=%s request_id=%s",
                user.id,
                user.partner_id.id,
                len(warehouse_ids),
                request_id,
                extra={"request_id": request_id},
            )
            role = _mxm_role_for_user(user)
            data = {
                "uid": user.id,
                "partner_id": user.partner_id.id,
                "access_token": access_token,
                "expires_in": 604800,
                "role": role,
                "warehouse_ids": warehouse_ids,
            }
            _enrich_login_data(env, data, request=http.request, app_hint="driver")
            return ok(data=data, request_id=request_id)
        except Exception as e:
            _logger.exception(
                "driver.auth.login error: %s request_id=%s",
                e,
                request_id,
                extra={"request_id": request_id},
            )
            _logger.debug(
                "driver.auth.login traceback request_id=%s:\n%s",
                request_id,
                traceback.format_exc(),
                extra={"request_id": request_id},
            )
            return fail_payload(
                message="Internal error",
                code="INTERNAL_ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/driver/auth/me",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def me(self, **kwargs):
        """GET /api/v1/driver/auth/me – Bearer; return uid, partner_id, role, warehouse_ids. 403 if not driver."""
        request_id = get_request_id()
        try:
            _logger.info(
                "driver.auth.me called request_id=%s",
                request_id,
                extra={"request_id": request_id},
            )
            ICP = http.request.env["ir.config_parameter"].sudo()
            if ICP.get_param(DRIVER_API_DISABLED_KEY, "0").lower() in ("1", "true"):
                return _driver_disabled_response(request_id)

            user, wh_ids, err = _require_driver(request_id)
            if err is not None:
                return err
            role = _mxm_role_for_user(user)
            return ok(
                data={
                    "uid": user.id,
                    "partner_id": user.partner_id.id,
                    "role": role,
                    "warehouse_ids": wh_ids,
                },
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "driver.auth.me error: %s request_id=%s",
                e,
                request_id,
                extra={"request_id": request_id},
            )
            return fail_payload(
                message="Internal error",
                code="INTERNAL_ERROR",
                http_status=500,
                request_id=request_id,
            )


class DriverOrdersAPI(http.Controller):
    """Drive App orders: list and detail, warehouse-scoped."""

    @http.route(
        "/api/v1/driver/orders",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def list_orders(self, limit=50, offset=0, **kwargs):
        """GET /api/v1/driver/orders – list orders for user's warehouses. 403 if not driver or no warehouses."""
        request_id = get_request_id()
        try:
            _logger.info(
                "driver.orders.list called request_id=%s",
                request_id,
                extra={"request_id": request_id},
            )
            ICP = http.request.env["ir.config_parameter"].sudo()
            if ICP.get_param(DRIVER_API_DISABLED_KEY, "0").lower() in ("1", "true"):
                return _driver_disabled_response(request_id)

            user, wh_ids, err = _require_driver(request_id)
            if err is not None:
                return err

            try:
                limit = min(int(limit), LIST_LIMIT_MAX) if limit else 50
            except (TypeError, ValueError):
                limit = 50
            try:
                offset = max(0, int(offset)) if offset else 0
            except (TypeError, ValueError):
                offset = 0

            env = http.request.env
            SaleOrder = env["sale.order"].sudo()
            domain = [("warehouse_id", "in", wh_ids)]
            orders = SaleOrder.search(
                domain,
                order="date_order desc, id desc",
                limit=limit,
                offset=offset,
            )
            items = [_order_to_item(o) for o in orders]
            total = SaleOrder.search_count(domain)
            meta = {"count": len(items), "total": total, "limit": limit, "offset": offset}

            _logger.info(
                "driver.orders.list uid=%s request_id=%s count=%s total=%s",
                user.id,
                request_id,
                len(items),
                total,
                extra={"request_id": request_id},
            )
            return ok(data=items, meta=meta, request_id=request_id)
        except Exception as e:
            _logger.exception(
                "driver.orders.list error: %s request_id=%s",
                e,
                request_id,
                extra={"request_id": request_id},
            )
            return fail_payload(
                message="Internal error",
                code="INTERNAL_ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/driver/orders/<int:order_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def get_order(self, order_id, **kwargs):
        """GET /api/v1/driver/orders/<order_id> – order detail. 403 if order not in user's warehouses."""
        request_id = get_request_id()
        try:
            _logger.info(
                "driver.orders.detail order_id=%s request_id=%s",
                order_id,
                request_id,
                extra={"request_id": request_id},
            )
            ICP = http.request.env["ir.config_parameter"].sudo()
            if ICP.get_param(DRIVER_API_DISABLED_KEY, "0").lower() in ("1", "true"):
                return _driver_disabled_response(request_id)

            user, wh_ids, err = _require_driver(request_id)
            if err is not None:
                return err

            env = http.request.env
            SaleOrder = env["sale.order"].sudo()
            order = SaleOrder.browse(order_id)
            order_exists = order.exists()
            if not order_exists:
                count_in_db = SaleOrder.search_count([("id", "=", order_id)])
                _logger.warning(
                    "driver.orders.detail NOT_FOUND order_id=%s user_id=%s order_exists=False search_count_id=%s request_id=%s",
                    order_id,
                    user.id,
                    count_in_db,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail_payload(
                    message="Order not found",
                    code="NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            if not order_in_warehouse_scope(order, user):
                _logger.warning(
                    "driver.orders.detail FORBIDDEN scope mismatch order_id=%s user_id=%s order_warehouse_id=%s request_id=%s",
                    order_id,
                    user.id,
                    order.warehouse_id.id if order.warehouse_id else None,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail_payload(
                    message="Forbidden",
                    code="FORBIDDEN",
                    http_status=403,
                    request_id=request_id,
                )
            base_url = (http.request.httprequest.url_root or "").rstrip("/")
            data = _order_to_detail(order, base_url)
            return ok(data=data, request_id=request_id)
        except Exception as e:
            _logger.exception(
                "[driver.orders.detail] INTERNAL_ERROR request_id=%s order_id=%s exception=%s",
                request_id,
                order_id,
                e,
                extra={"request_id": request_id},
            )
            return fail_payload(
                message="Internal error",
                code="INTERNAL_ERROR",
                http_status=500,
                request_id=request_id,
            )


class DriverDeliveryAPI(http.Controller):
    """Drive App delivery: GET and POST status, warehouse-scoped."""

    @http.route(
        "/api/v1/driver/orders/<int:order_id>/delivery",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def get_delivery(self, order_id, **kwargs):
        """GET /api/v1/driver/orders/<order_id>/delivery – delivery status. 403 if order not in scope."""
        request_id = get_request_id()
        try:
            _logger.info(
                "driver.delivery.get order_id=%s request_id=%s",
                order_id,
                request_id,
                extra={"request_id": request_id},
            )
            ICP = http.request.env["ir.config_parameter"].sudo()
            if ICP.get_param(DRIVER_API_DISABLED_KEY, "0").lower() in ("1", "true"):
                return _driver_disabled_response(request_id)

            user, wh_ids, err = _require_driver(request_id)
            if err is not None:
                return err

            env = http.request.env
            SaleOrder = env["sale.order"].sudo()
            order = SaleOrder.browse(order_id)
            order_exists = order.exists()
            if not order_exists:
                count_in_db = SaleOrder.search_count([("id", "=", order_id)])
                _logger.warning(
                    "driver.delivery.get NOT_FOUND order_id=%s user_id=%s order_exists=False search_count_id=%s request_id=%s",
                    order_id,
                    user.id,
                    count_in_db,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail_payload(
                    message="Order not found",
                    code="NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            if not order_in_warehouse_scope(order, user):
                _logger.warning(
                    "driver.delivery.get FORBIDDEN scope mismatch order_id=%s user_id=%s order_warehouse_id=%s request_id=%s",
                    order_id,
                    user.id,
                    order.warehouse_id.id if order.warehouse_id else None,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail_payload(
                    message="Forbidden",
                    code="FORBIDDEN",
                    http_status=403,
                    request_id=request_id,
                )
            order._mxm_ensure_initial_delivery_status()
            order.invalidate_recordset()
            data = _delivery_payload(order, request_id)
            return ok(data=data, request_id=request_id)
        except Exception as e:
            _logger.exception(
                "[driver.delivery.get] INTERNAL_ERROR request_id=%s order_id=%s exception=%s",
                request_id,
                order_id,
                e,
                extra={"request_id": request_id},
            )
            return fail_payload(
                message="Internal error",
                code="INTERNAL_ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/driver/orders/<int:order_id>/delivery/status",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def post_delivery_status(self, order_id, **kwargs):
        """POST /api/v1/driver/orders/<order_id>/delivery/status – set status. 403 if order not in scope."""
        request_id = get_request_id()
        user = None
        status = None
        note = None
        try:
            _logger.info(
                "driver.delivery.post_status order_id=%s request_id=%s",
                order_id,
                request_id,
                extra={"request_id": request_id},
            )
            ICP = http.request.env["ir.config_parameter"].sudo()
            if ICP.get_param(DRIVER_API_DISABLED_KEY, "0").lower() in ("1", "true"):
                return _driver_disabled_response(request_id)

            user, wh_ids, err = _require_driver(request_id)
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
            status = (body.get("status") or body.get("code") or "").strip().lower()
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
            order_exists = order.exists()
            user_wh_ids = list(wh_ids) if wh_ids else []
            # Diagnosis: log before any NOT_FOUND / FORBIDDEN so we can tell "no record" vs "scope mismatch"
            _logger.info(
                "driver.delivery.post_status lookup order_id=%s user_id=%s user_x_warehouse_ids=%s "
                "order_exists=%s request_id=%s",
                order_id,
                user.id,
                user_wh_ids,
                order_exists,
                request_id,
                extra={"request_id": request_id},
            )
            if order_exists:
                order_warehouse_id = order.warehouse_id.id if order.warehouse_id else None
                order_warehouse_name = order.warehouse_id.name if order.warehouse_id else None
                in_scope = order_in_warehouse_scope(order, user)
                _logger.info(
                    "driver.delivery.post_status scope order_id=%s order_warehouse_id=%s "
                    "order_warehouse_name=%s in_scope=%s request_id=%s",
                    order_id,
                    order_warehouse_id,
                    order_warehouse_name,
                    in_scope,
                    request_id,
                    extra={"request_id": request_id},
                )
                if order.warehouse_id is None or not order.warehouse_id.exists():
                    _logger.warning(
                        "driver.delivery.post_status ORDER_MISSING_WAREHOUSE_ID order_id=%s "
                        "order exists but warehouse_id is not set (mobile/MXM orders must set warehouse at checkout) request_id=%s",
                        order_id,
                        request_id,
                        extra={"request_id": request_id},
                    )
            if not order_exists:
                # Distinguish: id not in DB vs browse returned empty (e.g. record rules in rare cases)
                count_in_db = SaleOrder.search_count([("id", "=", order_id)])
                _logger.warning(
                    "driver.delivery.post_status NOT_FOUND order_id=%s user_id=%s user_x_warehouse_ids=%s "
                    "order_exists=False search_count_id=%s request_id=%s",
                    order_id,
                    user.id,
                    user_wh_ids,
                    count_in_db,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail_payload(
                    message="Order not found",
                    code="NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            # Order exists: scope mismatch must return FORBIDDEN (not NOT_FOUND)
            if not order_in_warehouse_scope(order, user):
                _logger.warning(
                    "driver.delivery.post_status FORBIDDEN scope mismatch order_id=%s user_id=%s "
                    "user_x_warehouse_ids=%s order_warehouse_id=%s request_id=%s",
                    order_id,
                    user.id,
                    user_wh_ids,
                    order.warehouse_id.id if order.warehouse_id else None,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail_payload(
                    message="Forbidden",
                    code="FORBIDDEN",
                    http_status=403,
                    request_id=request_id,
                )
            before_status = order.mxm_delivery_status or order.mxm_last_status_code
            ok_set, err_msg, error_code, stock_effect = order.sudo()._mxm_set_status(
                status,
                note=note,
                source="drive_app",
                user_id=user.id,
            )
            if not ok_set:
                _logger.warning(
                    "driver.delivery.post_status validation failed order_id=%s user_id=%s "
                    "warehouse_ids=%s request_id=%s message=%s code=%s",
                    order_id,
                    user.id,
                    wh_ids,
                    request_id,
                    err_msg or "",
                    error_code or "",
                    extra={"request_id": request_id},
                )
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
        except (UserError, ValidationError) as e:
            err_msg = str(e)
            code = "VALIDATION_ERROR"
            if "No delivery picking" in err_msg or "NO_DELIVERY_PICKING" in err_msg:
                code = "NO_DELIVERY_PICKING"
            elif "Insufficient stock" in err_msg or "OUT_OF_STOCK" in err_msg:
                code = "OUT_OF_STOCK"
            _logger.warning(
                "[driver.delivery.post_status] request_id=%s user_id=%s order_id=%s status=%s "
                "business validation: %s",
                request_id,
                user.id if user else None,
                order_id,
                status,
                err_msg,
                extra={"request_id": request_id},
            )
            http_status = 409 if code == "OUT_OF_STOCK" else 400
            return fail_payload(
                message=err_msg or "Validation failed",
                code=code,
                http_status=http_status,
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "[driver.delivery.post_status] INTERNAL_ERROR request_id=%s user_id=%s order_id=%s "
                "status=%s note=%s exception=%s",
                request_id,
                user.id if user else None,
                order_id,
                status,
                note,
                e,
                extra={"request_id": request_id},
            )
            return fail_payload(
                message="Internal error",
                code="INTERNAL_ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/driver/orders/<int:order_id>/cod/confirm",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def post_cod_confirm(self, order_id, **kwargs):
        """POST /api/v1/driver/orders/<order_id>/cod/confirm – driver confirms COD cash. No invoice created."""
        request_id = get_request_id()
        try:
            ICP = http.request.env["ir.config_parameter"].sudo()
            if ICP.get_param(DRIVER_API_DISABLED_KEY, "0").lower() in ("1", "true"):
                return _driver_disabled_response(request_id)
            user, wh_ids, err = _require_driver(request_id)
            if err is not None:
                return err
            ct = (http.request.httprequest.content_type or "").strip().lower()
            raw = http.request.httprequest.get_data(as_text=True) or "{}"
            body = json.loads(raw) if "application/json" in ct and raw.strip() else {}
            if not isinstance(body, dict):
                body = {}
            amount = body.get("amount")
            note = (body.get("note") or "").strip() or None
            env = http.request.env
            order = env["sale.order"].sudo().browse(order_id)
            if not order.exists():
                return fail_payload(message="Order not found", code="NOT_FOUND", http_status=404, request_id=request_id)
            if not order_in_warehouse_scope(order, user):
                return fail_payload(message="Forbidden", code="FORBIDDEN", http_status=403, request_id=request_id)
            if (getattr(order, "x_payment_method", None) or "") != "cod":
                return fail_payload(
                    message="Order is not COD",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            cur = getattr(order, "mxm_delivery_status", None) or getattr(order, "mxm_last_status_code", None)
            if cur not in COD_CONFIRM_ALLOWED_STATUSES:
                return fail_payload(
                    message="Order state does not allow COD confirm",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            ok_result, data = order._action_cod_confirm_driver(amount=amount, note=note, user_id=user.id)
            if not ok_result:
                return fail_payload(
                    message=data or "COD confirm failed",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            return ok(data=data, request_id=request_id)
        except Exception as e:
            _logger.exception(
                "driver.cod_confirm error order_id=%s request_id=%s: %s",
                order_id,
                request_id,
                e,
                extra={"request_id": request_id},
            )
            return fail_payload(
                message="Internal error",
                code="INTERNAL_ERROR",
                http_status=500,
                request_id=request_id,
            )
