# -*- coding: utf-8 -*-
"""
Lucky Wheel API: spin and redeem/verify.
"""
import json
import logging

from odoo import http
from odoo.http import request

from odoo.addons.inguumel_mobile_api.controllers.base import (
    get_request_id,
    ok,
    fail,
)

from odoo.addons.inguumel_lucky_wheel.services.spin_service import SpinServiceError

_logger = logging.getLogger(__name__)


def _parse_json_body(req, request_id):
    ct = (req.httprequest.content_type or "").strip().lower()
    if "application/json" not in ct:
        return None, fail(
            message="Invalid JSON",
            code="INVALID_JSON",
            http_status=400,
            request_id=request_id,
        )
    raw = req.httprequest.get_data(as_text=True)
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


def _is_redeem_allowed(user):
    """True if user can redeem (POS/delivery staff/admin)."""
    if user._is_public():
        return False
    if user.has_group("base.group_system"):
        return True
    if getattr(user, "x_warehouse_ids", None) and user.x_warehouse_ids:
        return True
    if user.has_group("sales_team.group_sale_salesman"):
        return True
    return False


class LuckyWheelAPI(http.Controller):
    """Lucky Wheel endpoints."""

    @http.route(
        "/api/v1/lucky-wheel/eligibility",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def eligibility(self, warehouse_id=None, **kwargs):
        """GET /api/v1/lucky-wheel/eligibility?warehouse_id=X – returns spin_credits, eligible, etc."""
        request_id = get_request_id()
        try:
            user = request.env.user
            if not user or user._is_public():
                return fail(
                    message="Unauthorized",
                    code="UNAUTHORIZED",
                    http_status=401,
                    request_id=request_id,
                )
            if not warehouse_id:
                return fail(
                    message="warehouse_id is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            try:
                warehouse_id = int(warehouse_id)
            except (TypeError, ValueError):
                return fail(
                    message="warehouse_id must be an integer",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            Config = request.env["lucky.wheel.config"].sudo()
            config = Config.search([
                ("warehouse_id", "=", warehouse_id),
                ("active", "=", True),
            ], limit=1)
            if not config:
                return fail(
                    message="Lucky Wheel not configured for this warehouse",
                    code="lucky_wheel_not_configured",
                    http_status=404,
                    request_id=request_id,
                )
            Spend = request.env["lucky.wheel.spend"].sudo()
            spend = Spend.get_or_create(user.id, warehouse_id)
            spend._recompute_accumulated()
            eligible = spend.computed_spin_credits > 0
            return ok(
                data={
                    "threshold_amount": config.threshold_amount,
                    "accumulated_paid_amount": spend.accumulated_paid_amount,
                    "spin_credits": spend.computed_spin_credits,
                    "eligible": eligible,
                },
                message="OK",
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "lucky_wheel.eligibility INTERNAL_ERROR request_id=%s: %s",
                request_id,
                e,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="INTERNAL_ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/lucky-wheel/spin",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def spin(self, **kwargs):
        """POST /api/v1/lucky-wheel/spin – Bearer auth, requires warehouse_id and Idempotency-Key header."""
        request_id = get_request_id()
        try:
            user = request.env.user
            if not user or user._is_public():
                return fail(
                    message="Unauthorized",
                    code="UNAUTHORIZED",
                    http_status=401,
                    request_id=request_id,
                )

            idempotency_key = request.httprequest.headers.get("Idempotency-Key") or request.httprequest.headers.get("idempotency-key")
            if not idempotency_key or not str(idempotency_key).strip():
                return fail(
                    message="Idempotency-Key header is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )

            data, err = _parse_json_body(request, request_id)
            if err is not None:
                return err

            warehouse_id = data.get("warehouse_id")
            if warehouse_id is None:
                return fail(
                    message="warehouse_id is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            try:
                warehouse_id = int(warehouse_id)
            except (TypeError, ValueError):
                return fail(
                    message="warehouse_id must be an integer",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )

            SpinService = request.env["lucky.wheel.spin.service"]
            result = SpinService.spin(
                user_id=user.id,
                warehouse_id=warehouse_id,
                idempotency_key=str(idempotency_key).strip(),
                request_id=request_id,
            )

            return ok(
                data=result,
                message="OK",
                request_id=request_id,
            )

        except SpinServiceError as e:
            _logger.info(
                "lucky_wheel.spin SpinServiceError code=%s request_id=%s",
                e.code,
                request_id,
                extra={"request_id": request_id},
            )
            status = 503 if e.code == "SERVICE_UNAVAILABLE" else 400
            return fail(
                message=e.message,
                code=e.code,
                http_status=status,
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "lucky_wheel.spin INTERNAL_ERROR request_id=%s: %s",
                request_id,
                e,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="INTERNAL_ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/lucky-wheel/redeem/verify",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def redeem_verify(self, **kwargs):
        """POST /api/v1/lucky-wheel/redeem/verify – verify OTP and mark prize redeemed."""
        request_id = get_request_id()
        try:
            user = request.env.user
            if not user or user._is_public():
                return fail(
                    message="Unauthorized",
                    code="UNAUTHORIZED",
                    http_status=401,
                    request_id=request_id,
                )
            if not _is_redeem_allowed(user):
                return fail(
                    message="Forbidden",
                    code="FORBIDDEN",
                    http_status=403,
                    request_id=request_id,
                )

            data, err = _parse_json_body(request, request_id)
            if err is not None:
                return err

            prize_id = data.get("prize_id")
            otp = data.get("otp")
            redeem_channel = data.get("redeem_channel", "pos")

            if prize_id is None:
                return fail(
                    message="prize_id is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            try:
                prize_id = int(prize_id)
            except (TypeError, ValueError):
                return fail(
                    message="prize_id must be an integer",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            if redeem_channel not in ("pos", "delivery", "admin"):
                redeem_channel = "pos"

            Prize = request.env["lucky.wheel.prize"].sudo()
            prize = Prize.browse(prize_id)
            if not prize.exists():
                return fail(
                    message="Prize not found",
                    code="NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )

            if prize.state not in ("won", "pending"):
                return fail(
                    message="Prize already redeemed or expired",
                    code="INVALID_STATE",
                    http_status=400,
                    request_id=request_id,
                )

            if not prize.verify_otp(str(otp or "")):
                return fail(
                    message="Invalid OTP",
                    code="INVALID_OTP",
                    http_status=400,
                    request_id=request_id,
                )

            from odoo import fields

            prize.write({
                "state": "redeemed",
                "redeemed_at": fields.Datetime.now(),
                "redeemed_by_user_id": user.id,
                "redeem_channel": redeem_channel,
            })

            if prize.prize_type == "product" and prize.product_id and prize.warehouse_id:
                prize._create_stock_move_for_product(prize.warehouse_id)

            return ok(
                data={
                    "prize_id": prize.id,
                    "state": "redeemed",
                    "redeemed_at": prize.redeemed_at,
                    "redeem_channel": redeem_channel,
                },
                message="Redeemed",
                request_id=request_id,
            )

        except Exception as e:
            _logger.exception(
                "lucky_wheel.redeem_verify INTERNAL_ERROR request_id=%s: %s",
                request_id,
                e,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="INTERNAL_ERROR",
                http_status=500,
                request_id=request_id,
            )
