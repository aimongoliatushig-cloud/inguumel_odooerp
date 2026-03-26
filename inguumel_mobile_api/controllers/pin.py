# -*- coding: utf-8 -*-
"""
Phone-only PIN login: request PIN, verify PIN (POST /api/v1/auth/pin/request, /pin/verify).
"""
import hashlib
import json
import logging
import random
import secrets
from datetime import timedelta

from odoo import http, fields
from odoo.addons.inguumel_mobile_api.controllers.base import (
    get_request_id,
    ok,
    fail,
    ok_payload,
    fail_payload_dict,
)

_logger = logging.getLogger(__name__)

PIN_TTL_SECONDS = 300
RATE_LIMIT_WINDOW_MINUTES = 10
RATE_LIMIT_MAX_REQUESTS = 5
MAX_PIN_ATTEMPTS = 5
PIN_DIGITS = 6


def _parse_json_body(request, request_id):
    """Parse JSON body when Content-Type is application/json. Returns (data, error_response)."""
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


def _ensure_pin_salt(env):
    """Get auth_pin.salt from config; if missing, generate and store once."""
    ICP = env["ir.config_parameter"].sudo()
    salt = (ICP.get_param("auth_pin.salt") or "").strip()
    if not salt:
        salt = secrets.token_hex(32)
        ICP.set_param("auth_pin.salt", salt)
    return salt


def _hash_pin_verify(pin_str, phone, salt):
    """Hash used for auth_pin (temporary PINs): sha256(pin + ':' + phone + ':' + salt)."""
    payload = "{}:{}:{}".format(pin_str, phone, salt)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_pin_register(pin_str, phone, salt):
    """Hash used for partner.x_pin_hash (registration): sha256(pin + phone + salt)."""
    payload = pin_str + phone + salt
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuthPinAPI(http.Controller):
    """PIN request endpoint."""

    @http.route(
        "/api/v1/auth/pin/request",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def pin_request(self, **kwargs):
        """POST /api/v1/auth/pin/request – send JSON {phone} to get a PIN (or dev_pin in dev_mode)."""
        request_id = get_request_id()
        try:
            _logger.info(
                "auth.pin.request called",
                extra={"request_id": request_id},
            )
            data, err = _parse_json_body(http.request, request_id)
            if err is not None:
                return err

            phone = (data.get("phone") or "")
            if isinstance(phone, str):
                phone = phone.strip()
            else:
                phone = None

            if not phone:
                return fail(
                    message="phone is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )

            env = http.request.env
            Partner = env["res.partner"]
            if "phone" not in Partner._fields:
                return fail(
                    message="User not found",
                    code="USER_NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )

            User = env["res.users"].sudo()
            user = User.search(
                [("partner_id.phone", "=", phone), ("active", "=", True)],
                limit=1,
            )
            if not user:
                _logger.info(
                    "auth.pin.request user not found phone=*** request_id=%s",
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail(
                    message="User not found",
                    code="USER_NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )

            # Rate limit: max 5 requests per phone in last 10 minutes
            AuthPin = env["inguumel.auth_pin"].sudo()
            window_start = fields.Datetime.now() - timedelta(minutes=RATE_LIMIT_WINDOW_MINUTES)
            recent_count = AuthPin.search_count([
                ("phone", "=", phone),
                ("create_date", ">=", window_start),
            ])
            if recent_count >= RATE_LIMIT_MAX_REQUESTS:
                _logger.warning(
                    "auth.pin.request rate limited phone=*** request_id=%s",
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail(
                    message="Too many requests",
                    code="RATE_LIMITED",
                    http_status=429,
                    request_id=request_id,
                )

            pin = str(random.randint(100000, 999999))
            salt = _ensure_pin_salt(env)
            pin_hash = _hash_pin_verify(pin, phone, salt)
            expires_at = fields.Datetime.now() + timedelta(seconds=PIN_TTL_SECONDS)

            AuthPin.create({
                "phone": phone,
                "user_id": user.id,
                "pin_hash": pin_hash,
                "expires_at": expires_at,
                "request_id": request_id,
            })

            dev_mode = env["ir.config_parameter"].sudo().get_param("auth_pin.dev_mode") == "True"
            response_data = {
                "phone": phone,
                "expires_in": PIN_TTL_SECONDS,
            }
            if dev_mode:
                response_data["dev_pin"] = pin

            return ok(
                data=response_data,
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "auth.pin.request error: %s",
                e,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/auth/pin/verify",
        type="json",
        auth="public",
        methods=["POST"],
        csrf=False,
    )
    def pin_verify(self, phone=None, pin=None, request_id=None, **kwargs):
        """POST /api/v1/auth/pin/verify – verify PIN and create session. Params: phone, pin, request_id (optional)."""
        req_id = get_request_id()
        env = http.request.env
        try:
            _logger.info(
                "auth.pin.verify called",
                extra={"request_id": req_id},
            )
            phone = (phone or "").strip() if isinstance(phone, str) else None
            if not phone:
                _logger.info("auth.pin.verify validation failed: phone missing request_id=%s", req_id, extra={"request_id": req_id})
                return fail_payload_dict(
                    message="phone is required",
                    code="VALIDATION_ERROR",
                    request_id=req_id,
                )
            pin_str = pin if pin is not None else ""
            if not isinstance(pin_str, str):
                pin_str = str(pin_str)
            if len(pin_str) != PIN_DIGITS or not pin_str.isdigit():
                _logger.info("auth.pin.verify validation failed: pin must be 6 digits request_id=%s", req_id, extra={"request_id": req_id})
                return fail_payload_dict(
                    message="pin must be exactly 6 digits",
                    code="VALIDATION_ERROR",
                    request_id=req_id,
                )

            # Try partner.x_pin_hash first (registration PIN, no auth_pin record)
            Partner = env["res.partner"].sudo()
            if "x_pin_hash" in Partner._fields and "phone" in Partner._fields:
                partner = Partner.search([("phone", "=", phone)], limit=1)
                if partner and partner.x_pin_hash:
                    salt = _ensure_pin_salt(env)
                    computed = _hash_pin_register(pin_str, phone, salt)
                    if computed == partner.x_pin_hash:
                        user = env["res.users"].sudo().search([("partner_id", "=", partner.id), ("active", "=", True)], limit=1)
                        display_phone = getattr(partner, "phone", None) or phone
                        if user:
                            session = http.request.session
                            session["pre_login"] = user.login
                            session["pre_uid"] = user.id
                            session.finalize(env(user=user.id))
                            _logger.info("auth.pin.verify success (partner pin) user_id=%s request_id=%s", user.id, req_id, extra={"request_id": req_id})
                            return ok_payload(
                                data={"user": {"id": user.id, "name": user.name, "phone": display_phone}},
                                request_id=req_id,
                            )
                        # Partner-only (no res.users): store in session, return partner as user
                        sess = http.request.session
                        sess["auth_partner_id"] = partner.id
                        sess["auth_phone"] = display_phone
                        _logger.info("auth.pin.verify success (partner pin) partner_id=%s request_id=%s", partner.id, req_id, extra={"request_id": req_id})
                        return ok_payload(
                            data={"user": {"id": partner.id, "name": partner.name, "phone": display_phone}},
                            request_id=req_id,
                        )

            now = fields.Datetime.now()
            AuthPin = env["inguumel.auth_pin"].sudo()
            domain = [
                ("phone", "=", phone),
                ("consumed", "=", False),
                ("expires_at", ">", now),
            ]
            if request_id:
                domain.append(("request_id", "=", request_id))
            record = AuthPin.search(domain, order="id desc", limit=1)
            if not record:
                _logger.info(
                    "auth.pin.verify PIN not found or expired phone=*** request_id=%s",
                    req_id,
                    extra={"request_id": req_id},
                )
                return fail_payload_dict(
                    message="PIN not found or expired",
                    code="PIN_NOT_FOUND_OR_EXPIRED",
                    request_id=req_id,
                )

            if record.attempts >= MAX_PIN_ATTEMPTS:
                record.consumed = True
                _logger.warning(
                    "auth.pin.verify too many attempts phone=*** request_id=%s",
                    req_id,
                    extra={"request_id": req_id},
                )
                return fail_payload_dict(
                    message="Too many attempts",
                    code="TOO_MANY_ATTEMPTS",
                    request_id=req_id,
                )

            salt = _ensure_pin_salt(env)
            computed_hash = _hash_pin_verify(pin_str, phone, salt)
            if computed_hash != record.pin_hash:
                record.attempts = record.attempts + 1
                _logger.info(
                    "auth.pin.verify invalid PIN phone=*** request_id=%s",
                    req_id,
                    extra={"request_id": req_id},
                )
                return fail_payload_dict(
                    message="Invalid PIN",
                    code="INVALID_PIN",
                    request_id=req_id,
                )

            record.consumed = True
            user = record.user_id
            session = http.request.session
            session["pre_login"] = user.login
            session["pre_uid"] = user.id
            session.finalize(env(user=user.id))

            display_phone = phone
            if hasattr(user.partner_id, "phone") and user.partner_id.phone:
                display_phone = user.partner_id.phone
            elif hasattr(user.partner_id, "mobile") and user.partner_id.mobile:
                display_phone = user.partner_id.mobile
            elif user.login:
                display_phone = user.login

            _logger.info(
                "auth.pin.verify success user_id=%s request_id=%s",
                user.id,
                req_id,
                extra={"request_id": req_id},
            )
            return ok_payload(
                data={
                    "user": {
                        "id": user.id,
                        "name": user.name,
                        "phone": display_phone,
                    },
                },
                request_id=req_id,
            )
        except Exception as e:
            _logger.exception(
                "auth.pin.verify error: %s",
                e,
                extra={"request_id": req_id},
            )
            return fail_payload_dict(
                message="Internal error",
                code="ERROR",
                request_id=req_id,
            )
