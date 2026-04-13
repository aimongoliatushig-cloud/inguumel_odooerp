# -*- coding: utf-8 -*-
"""
Auth API – register, login, me, logout as normal HTTP JSON (type="http").
"""
import json
import logging
import time
import traceback

from odoo import fields, http

from odoo.addons.inguumel_mobile_api.controllers.base import (
    get_request_id,
    ok,
    fail,
    fail_payload,
)
from odoo.addons.inguumel_mobile_api.controllers.pin import (
    _ensure_pin_salt,
    _hash_pin_register,
)

_logger = logging.getLogger(__name__)


def _mask_phone(phone):
    """Return masked phone for logging (never log full phone)."""
    if not phone or not isinstance(phone, str):
        return "***"
    phone = phone.strip()
    return ("***" + phone[-4:]) if len(phone) >= 4 else "***"


def _create_access_token(env, uid, request_id):
    """Create Bearer token for user. Returns token string or None on failure."""
    try:
        token = env["api.access.token"].sudo().create_token(uid)
    except Exception as token_err:
        _logger.exception(
            "auth _create_access_token failed uid=%s request_id=%s: %s",
            uid,
            request_id,
            token_err,
            extra={"request_id": request_id},
        )
        return None
    if not token or not isinstance(token, str) or not token.strip():
        _logger.error("auth _create_access_token empty uid=%s request_id=%s", uid, request_id)
        return None
    return token.strip()


def _is_warehouse_owner(user):
    """True if user has x_warehouse_ids (warehouse owner role). Safe if field missing (inguumel_order_mxm not installed)."""
    try:
        wh_ids = getattr(user, "x_warehouse_ids", None)
        return bool(wh_ids and wh_ids.ids)
    except Exception:
        return False


def _user_has_mxm_group(env, user, xml_id):
    """
    True if user belongs to the group identified by xml_id. Uses user.group_ids (Odoo 19)
    or user.groups_id so role detection works regardless of field name. Safe if group missing.
    """
    if not user or not user.id:
        return False
    try:
        group = env.ref(xml_id, raise_if_not_found=False)
        if not group or not group.exists():
            return False
        # Odoo 19 uses group_ids; fallback to groups_id for older versions
        user_groups = getattr(user, "group_ids", None) or getattr(user, "groups_id", None)
        if user_groups is None:
            return user.has_group(xml_id)
        return group in user_groups
    except Exception:
        return user.has_group(xml_id) if hasattr(user, "has_group") else False


def _mxm_role_for_user(user):
    """
    Determine role for mobile/driver/cashier apps from res.users group membership.
    Priority: admin > driver > cashier > warehouse_owner > staff > customer.
    MXM groups checked via _user_has_mxm_group so group_ids is used correctly.
    """
    if not user or not user.id:
        return "customer"
    env = user.env
    try:
        if user.has_group("base.group_system"):
            return "admin"
        if _user_has_mxm_group(env, user, "inguumel_order_mxm.group_driver"):
            return "driver"
        if _user_has_mxm_group(env, user, "inguumel_order_mxm.group_cash_confirm"):
            return "cashier"
        if _user_has_mxm_group(env, user, "inguumel_order_mxm.group_warehouse_owner") or _is_warehouse_owner(user):
            return "warehouse_owner"
        if user.has_group("stock.group_stock_user") or user.has_group("base.group_user"):
            return "staff"
    except Exception:
        pass
    return "customer"


def _mxm_roles_for_user(user):
    """All roles the user has (from group membership). Uses group_ids for MXM groups. No duplicates."""
    roles = []
    if not user or not user.id:
        return ["customer"]
    env = user.env
    try:
        if user.has_group("base.group_system"):
            roles.append("admin")
        if _user_has_mxm_group(env, user, "inguumel_order_mxm.group_driver"):
            roles.append("driver")
        if _user_has_mxm_group(env, user, "inguumel_order_mxm.group_cash_confirm"):
            roles.append("cashier")
        if _user_has_mxm_group(env, user, "inguumel_order_mxm.group_warehouse_owner") or _is_warehouse_owner(user):
            roles.append("warehouse_owner")
        if user.has_group("stock.group_stock_user") or user.has_group("base.group_user"):
            roles.append("staff")
    except Exception:
        pass
    if not roles:
        roles.append("customer")
    return roles


def _mxm_capabilities_for_user(user):
    """
    Strict role-specific capabilities. Cashier must NOT have driver capability.
    - can_driver_update_delivery_status: only group_driver or group_warehouse_owner.
    - can_cash_confirm: only admin or group_cash_confirm.
    - can_manage_warehouse: only admin, group_warehouse_owner, or x_warehouse_ids.
    """
    caps = {
        "can_driver_update_delivery_status": False,
        "can_cash_confirm": False,
        "can_manage_warehouse": False,
    }
    if not user or not user.id:
        return caps
    env = user.env
    try:
        has_admin = user.has_group("base.group_system")
        has_driver = _user_has_mxm_group(env, user, "inguumel_order_mxm.group_driver")
        has_cash_confirm = _user_has_mxm_group(env, user, "inguumel_order_mxm.group_cash_confirm")
        has_warehouse_owner_group = _user_has_mxm_group(env, user, "inguumel_order_mxm.group_warehouse_owner")
        is_wh_owner = _is_warehouse_owner(user)

        caps["can_cash_confirm"] = has_admin or has_cash_confirm
        caps["can_manage_warehouse"] = has_admin or has_warehouse_owner_group or is_wh_owner
        caps["can_driver_update_delivery_status"] = has_driver or has_warehouse_owner_group
    except Exception:
        pass
    return caps


def _mxm_primary_role(user, app_context=None, request=None, app_hint=None):
    """
    Primary role for this request. When app_context (or X-App header or ?app= query) is "driver" or "cashier",
    return that role if user has the capability; else priority: admin > cashier > driver > warehouse_owner > staff > customer.
    """
    roles = _mxm_roles_for_user(user)
    caps = _mxm_capabilities_for_user(user)
    app = app_context or app_hint
    if app is None and request is not None:
        try:
            h = getattr(request, "httprequest", None)
            if h:
                app = (h.headers.get("X-App") or "").strip().lower() or (h.args.get("app") or "").strip().lower()
        except Exception:
            pass
    if app == "driver" and caps.get("can_driver_update_delivery_status"):
        return "driver"
    if app == "cashier" and caps.get("can_cash_confirm"):
        return "cashier"
    for p in ("admin", "cashier", "driver", "warehouse_owner", "staff", "customer"):
        if p in roles:
            return p
    return "customer"


def _enrich_login_data(env, data, request=None, app_hint=None):
    """Add primary_role, roles, capabilities to login data. Keeps existing data['role'] (legacy) unchanged."""
    if not data or "uid" not in data:
        return
    try:
        user = env["res.users"].browse(data["uid"])
        if not user.exists():
            return
        data["roles"] = _mxm_roles_for_user(user)
        data["capabilities"] = _mxm_capabilities_for_user(user)
        data["primary_role"] = _mxm_primary_role(user, request=request, app_hint=app_hint)
        # Do not overwrite data["role"] – keep legacy single role for backward compatibility
    except Exception:
        pass


def _parse_json_body(request, request_id):
    """
    Parse JSON body from request. Prefer request.jsonrequest when available (type='json'),
    otherwise parse from raw body (type='http').
    Returns (data, error_response).
    """
    # Prefer jsonrequest when available (e.g. type='json2' routes)
    if hasattr(request, "jsonrequest") and request.jsonrequest is not None:
        data = request.jsonrequest if isinstance(request.jsonrequest, dict) else {}
        return data, None

    ct = (request.httprequest.content_type or "").strip().lower()
    if "application/json" not in ct:
        return None, fail(
            message="Invalid JSON",
            code="INVALID_JSON",
            http_status=400,
            request_id=request_id,
        )
    raw = request.httprequest.get_data(as_text=True)
    if not raw or not raw.strip():
        return None, fail(
            message="Invalid JSON",
            code="INVALID_JSON",
            http_status=400,
            request_id=request_id,
        )
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


def _auth_login_phone_pin(payload, request_id):
    """
    Perform phone+pin login (same logic as POST /api/v1/auth/login).
    Returns (data_dict, None) on success; (None, response) on error.
    data_dict: { uid, partner_id, access_token, expires_in, role, warehouse_ids }.
    Used by auth.login and by driver auth compatibility (POST /api/v1/driver/auth/login with {phone, pin}).
    """
    payload = payload or {}
    phone = (payload.get("phone") or "")
    phone = phone.strip() if isinstance(phone, str) else ""
    pin_str = (payload.get("pin") or "")
    pin_str = str(pin_str).strip()

    if not phone:
        return None, fail(
            message="phone is required",
            code="VALIDATION_ERROR",
            http_status=400,
            request_id=request_id,
        )
    if not pin_str:
        return None, fail(
            message="pin is required",
            code="VALIDATION_ERROR",
            http_status=400,
            request_id=request_id,
        )
    if len(pin_str) != 6 or not pin_str.isdigit():
        return None, fail(
            message="pin must be exactly 6 digits",
            code="VALIDATION_ERROR",
            http_status=400,
            request_id=request_id,
        )

    env = http.request.env
    User = env["res.users"].sudo()
    Partner = env["res.partner"].sudo()
    phone_masked = _mask_phone(phone)

    user = None
    matched_source = None
    partner = None

    # 1) Staff flow: try res.users by login=phone
    user = User.search([("active", "=", True), ("login", "=", phone)], limit=1)
    if user:
        matched_source = "user_login"

    # 2) Staff flow: try by partner.phone then partner.mobile
    if not user and "phone" in Partner._fields:
        user = User.search([("active", "=", True), ("partner_id.phone", "=", phone)], limit=1)
        if user:
            matched_source = "user_partner_phone"
    if not user and "mobile" in Partner._fields:
        user = User.search([("active", "=", True), ("partner_id.mobile", "=", phone)], limit=1)
        if user:
            matched_source = "user_partner_mobile"

    if user:
        credential = {"login": user.login, "password": pin_str, "type": "password"}
        try:
            auth_info = http.request.session.authenticate(env, credential)
            if auth_info and auth_info.get("uid"):
                partner = user.partner_id
                access_token = _create_access_token(env, user.id, request_id)
                if access_token is None:
                    return None, fail(
                        message="Internal error",
                        code="INTERNAL_ERROR",
                        http_status=500,
                        request_id=request_id,
                    )
                role = _mxm_role_for_user(user)
                warehouse_ids = list(user.x_warehouse_ids.ids) if _is_warehouse_owner(user) else []
                _logger.info(
                    "auth.login success uid=%s partner_id=%s role=%s matched_source=%s phone=%s request_id=%s",
                    user.id,
                    partner.id,
                    role,
                    matched_source,
                    phone_masked,
                    request_id,
                    extra={"request_id": request_id},
                )
                return (
                    {
                        "uid": user.id,
                        "partner_id": partner.id,
                        "access_token": access_token,
                        "expires_in": 604800,
                        "role": role,
                        "warehouse_ids": warehouse_ids,
                    },
                    None,
                )
        except Exception as auth_err:
            _logger.info(
                "auth.login INVALID_PIN identity=user matched_source=%s phone=%s request_id=%s err=%s",
                matched_source,
                phone_masked,
                request_id,
                auth_err,
                extra={"request_id": request_id},
            )
            return None, fail(
                message="Invalid credentials",
                code="INVALID_PIN",
                http_status=401,
                request_id=request_id,
            )

    # 3) Partner flow: mobile customers with phone + x_pin_hash
    if "phone" not in Partner._fields or "x_pin_hash" not in Partner._fields:
        _logger.info(
            "auth.login USER_NOT_FOUND no user partner.x_pin_hash unavailable phone=%s request_id=%s",
            phone_masked,
            request_id,
            extra={"request_id": request_id},
        )
        return None, fail(
            message="User not found",
            code="USER_NOT_FOUND",
            http_status=401,
            request_id=request_id,
        )

    partner = Partner.search([("phone", "=", phone)], limit=1)
    if not partner:
        _logger.info(
            "auth.login USER_NOT_FOUND no user no partner phone=%s request_id=%s",
            phone_masked,
            request_id,
            extra={"request_id": request_id},
        )
        return None, fail(
            message="User not found",
            code="USER_NOT_FOUND",
            http_status=401,
            request_id=request_id,
        )
    if not partner.x_pin_hash:
        _logger.info(
            "auth.login USER_NOT_FOUND partner has no x_pin_hash phone=%s request_id=%s",
            phone_masked,
            request_id,
            extra={"request_id": request_id},
        )
        return None, fail(
            message="User not found",
            code="USER_NOT_FOUND",
            http_status=401,
            request_id=request_id,
        )

    salt = _ensure_pin_salt(env)
    computed = _hash_pin_register(pin_str, phone, salt)
    if computed != partner.x_pin_hash:
        _logger.info(
            "auth.login INVALID_PIN identity=partner phone=%s request_id=%s",
            phone_masked,
            request_id,
            extra={"request_id": request_id},
        )
        return None, fail(
            message="Invalid credentials",
            code="INVALID_PIN",
            http_status=401,
            request_id=request_id,
        )

    matched_source = "partner"
    user = User.search([("partner_id", "=", partner.id), ("active", "=", True)], limit=1)
    if not user:
        portal_group = env.ref("base.group_portal")
        login = "mobile_%d" % partner.id
        user = User.with_context(no_reset_password=True).create({
            "name": partner.name or phone,
            "login": login,
            "password": pin_str,
            "partner_id": partner.id,
            "group_ids": [(6, 0, [portal_group.id])],
            "active": True,
        })

    credential = {"login": user.login, "password": pin_str, "type": "password"}
    try:
        auth_info = http.request.session.authenticate(env, credential)
        if not auth_info or not auth_info.get("uid"):
            raise ValueError("authenticate returned no uid")
    except Exception as auth_err:
        _logger.info(
            "auth.login INVALID_PIN identity=partner matched_source=%s phone=%s request_id=%s err=%s",
            matched_source,
            phone_masked,
            request_id,
            auth_err,
            extra={"request_id": request_id},
        )
        return None, fail(
            message="Invalid credentials",
            code="INVALID_PIN",
            http_status=401,
            request_id=request_id,
        )

    access_token = _create_access_token(env, user.id, request_id)
    if access_token is None:
        return None, fail(
            message="Internal error",
            code="INTERNAL_ERROR",
            http_status=500,
            request_id=request_id,
        )

    role = _mxm_role_for_user(user)
    warehouse_ids = list(user.x_warehouse_ids.ids) if _is_warehouse_owner(user) else []

    _logger.info(
        "auth.login success uid=%s partner_id=%s role=%s matched_source=%s phone=%s request_id=%s",
        user.id,
        partner.id,
        role,
        matched_source,
        phone_masked,
        request_id,
        extra={"request_id": request_id},
    )
    return (
        {
            "uid": user.id,
            "partner_id": partner.id,
            "access_token": access_token,
            "expires_in": 604800,
            "role": role,
            "warehouse_ids": warehouse_ids,
        },
        None,
    )


def _is_customer_only_user(user):
    """True only for customer/portal accounts; false for staff, drivers, cashiers, owners, admins."""
    roles = _mxm_roles_for_user(user)
    privileged_roles = {"admin", "staff", "warehouse_owner", "driver", "cashier"}
    return not any(role in privileged_roles for role in roles)


def _anonymize_mobile_customer_account(env, partner, user=None, request_id=None):
    """
    Deactivate the mobile customer account and anonymize personal data while
    keeping legally required transaction history intact.
    """
    partner = partner.sudo() if partner else None
    user = user.sudo() if user else None
    if not partner or not partner.exists():
        raise ValueError("Partner not found")

    suffix = "deleted_%s_%s" % (partner.id, int(time.time()))
    partner_vals = {
        "name": "Deleted customer %s" % partner.id,
    }
    for field_name in (
        "phone",
        "mobile",
        "email",
        "street",
        "street2",
        "city",
        "zip",
        "x_pin_hash",
        "x_phone_2",
        "x_default_warehouse_id",
        "x_aimag_id",
        "x_sum_id",
    ):
        if field_name in partner._fields:
            partner_vals[field_name] = False
    if "active" in partner._fields:
        partner_vals["active"] = False

    if user and user.exists():
        env["api.access.token"].sudo().search([("user_id", "=", user.id)]).unlink()
        user_vals = {
            "login": suffix,
            "active": False,
        }
        user.write(user_vals)
        try:
            if getattr(http.request.session, "uid", None) == user.id:
                http.request.session.logout(keep_db=True)
        except Exception:
            pass

    partner.write(partner_vals)

    _logger.info(
        "auth.account_delete success partner_id=%s user_id=%s request_id=%s deleted_at=%s",
        partner.id,
        user.id if user and user.exists() else None,
        request_id,
        fields.Datetime.now(),
        extra={"request_id": request_id},
    )
    return {
        "deleted": True,
        "retention_note": (
            "Personal profile data is anonymized, while order or accounting "
            "records may be retained when required by law."
        ),
    }


def _resolve_customer_delete_request(payload, request_id):
    """Resolve a customer account for public delete requests using phone + PIN."""
    payload = payload or {}
    phone = (payload.get("phone") or "")
    phone = phone.strip() if isinstance(phone, str) else ""
    pin_str = str(payload.get("pin") or "").strip()

    if not phone:
        return None, None, fail_payload(
            "phone is required",
            code="VALIDATION_ERROR",
            http_status=400,
            request_id=request_id,
        )
    if len(pin_str) != 6 or not pin_str.isdigit():
        return None, None, fail_payload(
            "pin must be exactly 6 digits",
            code="VALIDATION_ERROR",
            http_status=400,
            request_id=request_id,
        )

    env = http.request.env
    Partner = env["res.partner"].sudo()
    User = env["res.users"].sudo()

    if "phone" not in Partner._fields or "x_pin_hash" not in Partner._fields:
        return None, None, fail_payload(
            "Invalid credentials",
            code="INVALID_PIN",
            http_status=401,
            request_id=request_id,
        )

    partner = Partner.search([("phone", "=", phone)], limit=1)
    if not partner or not partner.x_pin_hash:
        return None, None, fail_payload(
            "Invalid credentials",
            code="INVALID_PIN",
            http_status=401,
            request_id=request_id,
        )

    salt = _ensure_pin_salt(env)
    computed = _hash_pin_register(pin_str, phone, salt)
    if computed != partner.x_pin_hash:
        return None, None, fail_payload(
            "Invalid credentials",
            code="INVALID_PIN",
            http_status=401,
            request_id=request_id,
        )

    user = User.search([("partner_id", "=", partner.id)], limit=1)
    if user and user.exists() and not _is_customer_only_user(user):
        return None, None, fail_payload(
            "This account must be deleted by an administrator.",
            code="FORBIDDEN",
            http_status=403,
            request_id=request_id,
        )
    return user, partner, None


class AuthAPI(http.Controller):
    """Auth endpoints: login, me, logout (HTTP JSON, no jsonrpc)."""

    @http.route(
        "/api/v1/auth/register",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def register(self, **kwargs):
        """POST /api/v1/auth/register – JSON { phone, pin, pin_confirm }. Creates res.partner and portal user (res.users)."""
        request_id = get_request_id()
        try:
            _logger.info("auth.register called", extra={"request_id": request_id})

            payload, err = _parse_json_body(http.request, request_id)
            if err is not None:
                return err

            payload = payload or {}
            phone = (payload.get("phone") or "")
            phone = phone.strip() if isinstance(phone, str) else ""
            pin_str = (payload.get("pin") or "")
            pin_str = str(pin_str).strip()
            pin_confirm_str = (payload.get("pin_confirm") or "")
            pin_confirm_str = str(pin_confirm_str).strip()

            if not phone:
                return fail_payload(
                    "phone is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            if not pin_str:
                return fail_payload(
                    "pin is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            if len(pin_str) != 6 or not pin_str.isdigit():
                return fail_payload(
                    "pin must be exactly 6 digits",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            if pin_str != pin_confirm_str:
                return fail_payload(
                    "pin and pin_confirm must match",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )

            env = http.request.env
            Partner = env["res.partner"].sudo()
            if "phone" not in Partner._fields:
                return fail_payload(
                    "res.partner.phone not available",
                    code="ERROR",
                    http_status=500,
                    request_id=request_id,
                )
            if "x_pin_hash" not in Partner._fields:
                return fail_payload(
                    "partner.x_pin_hash field missing",
                    code="ERROR",
                    http_status=500,
                    request_id=request_id,
                )

            # Create or get res.partner (customer)
            partner = Partner.search([("phone", "=", phone)], limit=1)
            if not partner:
                partner = Partner.create({"name": phone, "phone": phone})

            salt = _ensure_pin_salt(env)
            pin_hash = _hash_pin_register(pin_str, phone, salt)
            partner.write({"x_pin_hash": pin_hash})

            # Create or ensure portal user (res.users) – Odoo 19 uses group_ids
            User = env["res.users"].sudo()
            portal_group = env.ref("base.group_portal")
            user = User.search([("partner_id", "=", partner.id), ("active", "=", True)], limit=1)
            if not user:
                login = "mobile_%d" % partner.id
                user = User.with_context(no_reset_password=True).create({
                    "name": partner.name or phone,
                    "login": login,
                    "password": pin_str,
                    "partner_id": partner.id,
                    "group_ids": [(6, 0, [portal_group.id])],
                    "active": True,
                })
            else:
                user.write({"password": pin_str})

            return ok(
                data={"user_id": user.id, "partner_id": partner.id},
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception("auth.register error: %s", e, extra={"request_id": request_id})
            return fail_payload(
                "Internal error",
                code="ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/auth/account/delete_request",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def delete_account_request(self, **kwargs):
        """Public account deletion using phone + PIN for web deletion flows."""
        request_id = get_request_id()
        try:
            payload, err = _parse_json_body(http.request, request_id)
            if err is not None:
                return err

            user, partner, err = _resolve_customer_delete_request(payload, request_id)
            if err is not None:
                return err

            data = _anonymize_mobile_customer_account(
                http.request.env,
                partner,
                user=user,
                request_id=request_id,
            )
            return ok(data=data, message="ACCOUNT_DELETED", request_id=request_id)
        except Exception as e:
            _logger.exception(
                "auth.delete_account_request error: %s request_id=%s",
                e,
                request_id,
                extra={"request_id": request_id},
            )
            return fail_payload(
                "Internal error",
                code="ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/auth/account/delete",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def delete_account(self, **kwargs):
        """Authenticated in-app deletion for customer accounts."""
        request_id = get_request_id()
        try:
            uid = getattr(http.request.session, "uid", None)
            if not uid:
                return fail(
                    message="Unauthorized",
                    code="UNAUTHORIZED",
                    http_status=401,
                    request_id=request_id,
                )

            user = http.request.env["res.users"].sudo().browse(int(uid))
            partner = user.partner_id.sudo() if user and user.exists() else None
            if not user or not user.exists() or not partner or not partner.exists():
                return fail(
                    message="Unauthorized",
                    code="UNAUTHORIZED",
                    http_status=401,
                    request_id=request_id,
                )
            if not _is_customer_only_user(user):
                return fail(
                    message="This account must be deleted by an administrator.",
                    code="FORBIDDEN",
                    http_status=403,
                    request_id=request_id,
                )

            data = _anonymize_mobile_customer_account(
                http.request.env,
                partner,
                user=user,
                request_id=request_id,
            )
            return ok(data=data, message="ACCOUNT_DELETED", request_id=request_id)
        except Exception as e:
            _logger.exception(
                "auth.delete_account error: %s request_id=%s",
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
        "/api/v1/auth/login_pin",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def login_pin(self, **kwargs):
        """POST /api/v1/auth/login_pin – JSON { phone, pin }. Alias for login flow when res.users exists."""
        request_id = get_request_id()
        try:
            _logger.info("auth.login_pin called", extra={"request_id": request_id})
            payload, err = _parse_json_body(http.request, request_id)
            if err is not None:
                return err
            payload = payload or {}
            phone = (payload.get("phone") or "").strip() if isinstance(payload.get("phone"), str) else ""
            pin_str = str(payload.get("pin") or "").strip()
            if not phone:
                return fail_payload(
                    message="phone is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            if len(pin_str) != 6 or not pin_str.isdigit():
                return fail_payload(
                    message="pin must be exactly 6 digits",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            env = http.request.env
            Partner = env["res.partner"].sudo()
            if "phone" not in Partner._fields or "x_pin_hash" not in Partner._fields:
                return fail_payload(
                    message="Invalid credentials",
                    code="INVALID_PIN",
                    http_status=401,
                    request_id=request_id,
                )
            partner = Partner.search([("phone", "=", phone)], limit=1)
            if not partner or not partner.x_pin_hash:
                return fail_payload(
                    message="Invalid credentials",
                    code="INVALID_PIN",
                    http_status=401,
                    request_id=request_id,
                )
            salt = _ensure_pin_salt(env)
            computed = _hash_pin_register(pin_str, phone, salt)
            if computed != partner.x_pin_hash:
                return fail_payload(
                    message="Invalid PIN",
                    code="INVALID_PIN",
                    http_status=401,
                    request_id=request_id,
                )
            user = env["res.users"].sudo().search([("partner_id", "=", partner.id), ("active", "=", True)], limit=1)
            if not user:
                # Partner-only (no res.users): cart will return 401 until they use /auth/login with portal user
                display_phone = getattr(partner, "phone", None) or phone
                sess = http.request.session
                sess["auth_partner_id"] = partner.id
                sess["auth_phone"] = display_phone
                sid = sess.sid if hasattr(sess, "sid") and sess.sid else str(partner.id)
                return ok(
                    data={
                        "access_token": sid,
                        "expires_in": 604800,
                        "user": {"id": partner.id, "name": partner.name, "phone": display_phone},
                    },
                    request_id=request_id,
                )
            # Portal user exists: authenticate (same as /auth/login); Odoo post_dispatch sets session_id cookie
            credential = {"login": user.login, "password": pin_str, "type": "password"}
            try:
                auth_info = http.request.session.authenticate(env, credential)
                if auth_info and auth_info.get("uid"):
                    TokenModel = env["api.access.token"].sudo()
                    access_token = TokenModel.create_token(user.id)
                    access_token = (access_token or "").strip() if isinstance(access_token, str) else ""
                    if not access_token:
                        return fail_payload(
                            message="Internal error",
                            code="ERROR",
                            http_status=500,
                            request_id=request_id,
                        )
                    return ok(
                        data={
                            "uid": user.id,
                            "partner_id": partner.id,
                            "access_token": access_token,
                            "expires_in": 604800,
                            "user": {"id": user.id, "name": user.name, "phone": getattr(partner, "phone", None) or phone},
                        },
                        request_id=request_id,
                    )
            except Exception:
                pass
            # Fallback: legacy pre_login/pre_uid (no cookie)
            session = http.request.session
            session["pre_login"] = user.login
            session["pre_uid"] = user.id
            session.finalize(env(user=user.id))
            display_phone = getattr(partner, "phone", None) or phone
            return ok(
                data={
                    "access_token": session.sid,
                    "expires_in": 604800,
                    "user": {"id": user.id, "name": user.name, "phone": display_phone},
                },
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception("auth.login_pin error: %s", e, extra={"request_id": request_id})
            return fail_payload(
                message="Internal error",
                code="ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/auth/login",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def login(self, **kwargs):
        """POST /api/v1/auth/login – JSON { phone, pin }.
        Supports:
        - Staff users (login=phone or partner.phone/mobile): authenticate via password, no x_pin_hash.
        - Mobile customers (partner+phone+x_pin_hash): verify PIN hash, create portal user if needed.
        Returns uid, partner_id, access_token (Bearer).
        """
        request_id = get_request_id()
        try:
            _logger.info("auth.login called", extra={"request_id": request_id})

            payload, err = _parse_json_body(http.request, request_id)
            if err is not None:
                return err

            data, err = _auth_login_phone_pin(payload or {}, request_id)
            if err is not None:
                return err
            _enrich_login_data(http.request.env, data, request=http.request)
            return ok(data=data, request_id=request_id)
        except Exception as e:
            _logger.exception(
                "auth.login error: %s request_id=%s",
                e,
                request_id,
                extra={"request_id": request_id},
            )
            _logger.debug(
                "auth.login traceback request_id=%s:\n%s",
                request_id,
                traceback.format_exc(),
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="INTERNAL_ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/auth/logout",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def logout(self, **kwargs):
        """POST /api/v1/auth/logout – invalidate session. Idempotent if not logged in."""
        request_id = get_request_id()
        try:
            _logger.info(
                "auth.logout called",
                extra={"request_id": request_id},
            )
            if http.request.session.uid:
                http.request.session.logout(keep_db=True)
            return ok(message="LOGGED_OUT", request_id=request_id)
        except Exception as e:
            _logger.exception(
                "auth.logout error: %s request_id=%s",
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
        "/api/v1/auth/me",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def me(self, **kwargs):
        """GET /api/v1/auth/me – return current user or 401 if not logged in."""
        request_id = get_request_id()
        try:
            has_cookie = bool(
                http.request.httprequest.headers.get("Cookie")
                or http.request.httprequest.headers.get("cookie")
            )
            session_uid = getattr(http.request.session, "uid", None)
            _logger.info(
                "auth.me called has_cookie=%s session_uid=%s",
                has_cookie,
                session_uid,
                extra={"request_id": request_id},
            )
            if not http.request.session.uid:
                return fail(
                    message="Unauthorized",
                    code="UNAUTHORIZED",
                    http_status=401,
                    request_id=request_id,
                )
            uid = int(http.request.session.uid)
            user = http.request.env["res.users"].sudo().browse(uid)
            partner = user.partner_id.sudo() if user and user.exists() else None
            if not user or not user.exists():
                return fail(
                    message="Unauthorized",
                    code="UNAUTHORIZED",
                    http_status=401,
                    request_id=request_id,
                )
            phone_primary = ((partner.phone or partner.mobile or "") if partner else "").strip()
            phone_secondary = ((getattr(partner, "x_phone_2", None) or "") if partner else "").strip()
            delivery_address = ((partner.street or "") if partner else "").strip()
            city = ((partner.city or "") if partner else "").strip()
            aimag = getattr(partner, "x_aimag_id", None) if partner else None
            sum_rec = getattr(partner, "x_sum_id", None) if partner else None
            aimag_id = aimag.id if aimag and aimag.exists() else None
            sum_id = sum_rec.id if sum_rec and sum_rec.exists() else None
            return ok(
                data={
                    "uid": user.id,
                    "user_id": user.id,
                    "partner_id": partner.id if partner else None,
                    "name": (partner.name or user.name) if partner else (user.name or ""),
                    "login": user.login or "",
                    "phone_primary": phone_primary,
                    "phone_secondary": phone_secondary,
                    "delivery_address": delivery_address,
                    "city": city,
                    "aimag_id": aimag_id,
                    "sum_id": sum_id,
                },
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "auth.me error: %s request_id=%s",
                e,
                request_id,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="INTERNAL_ERROR",
                http_status=500,
                request_id=request_id,
            )
