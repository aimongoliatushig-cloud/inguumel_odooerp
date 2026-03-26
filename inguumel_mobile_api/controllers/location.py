# -*- coding: utf-8 -*-
"""
Location: set aimag/sum and resolve warehouse; public dropdowns from ingo.location.aimag/sum.
"""
import logging

from odoo import http

from odoo.addons.inguumel_mobile_api.controllers.base import (
    get_request_id,
    ok,
    fail,
    ok_payload,
    fail_payload_dict,
)

_logger = logging.getLogger(__name__)


class AuthLocationAPI(http.Controller):
    """Location set and dropdown endpoints."""

    @http.route(
        "/api/v1/auth/location/set",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def location_set(self, aimag_id=None, sum_id=None, **kwargs):
        """POST /api/v1/auth/location/set – set partner aimag/sum and resolve warehouse."""
        request_id = get_request_id()
        try:
            _logger.info(
                "auth.location.set called",
                extra={"request_id": request_id},
            )
            try:
                aimag_id = int(aimag_id) if aimag_id is not None else None
                sum_id = int(sum_id) if sum_id is not None else None
            except (TypeError, ValueError):
                aimag_id = sum_id = None
            if aimag_id is None or sum_id is None:
                return fail_payload_dict(
                    message="aimag_id and sum_id are required",
                    code="VALIDATION_ERROR",
                    request_id=request_id,
                )
            env = http.request.env
            Aimag = env["ingo.location.aimag"].sudo()
            Sum = env["ingo.location.sum"].sudo()
            if not Aimag.browse(aimag_id).exists():
                return fail_payload_dict(
                    message="Invalid aimag_id",
                    code="VALIDATION_ERROR",
                    request_id=request_id,
                )
            sum_rec = Sum.browse(sum_id)
            if not sum_rec.exists() or sum_rec.aimag_id.id != aimag_id:
                return fail_payload_dict(
                    message="Invalid sum_id or sum does not belong to aimag",
                    code="VALIDATION_ERROR",
                    request_id=request_id,
                )
            partner = env.user.partner_id.sudo()
            partner.write({"x_aimag_id": aimag_id, "x_sum_id": sum_id})
            Warehouse = env["stock.warehouse"].sudo()
            warehouse = Warehouse.search(
                [("x_sum_id", "=", sum_id)],
                limit=1,
            )
            if not warehouse:
                _logger.info(
                    "auth.location.set warehouse not found partner_id=%s sum_id=%s request_id=%s",
                    partner.id,
                    sum_id,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail_payload_dict(
                    message="No warehouse for this sum",
                    code="WAREHOUSE_NOT_FOUND",
                    request_id=request_id,
                )
            partner.write({"x_default_warehouse_id": warehouse.id})
            lot_stock_id = warehouse.lot_stock_id.id if warehouse.lot_stock_id else None
            _logger.info(
                "auth.location.set success partner_id=%s sum_id=%s warehouse_id=%s lot_stock_id=%s request_id=%s",
                partner.id,
                sum_id,
                warehouse.id,
                lot_stock_id,
                request_id,
                extra={"request_id": request_id},
            )
            return ok_payload(
                data={"warehouse_id": warehouse.id},
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "auth.location.set error: %s",
                e,
                extra={"request_id": request_id},
            )
            return fail_payload_dict(
                message="Internal error",
                code="ERROR",
                request_id=request_id,
            )

    @http.route(
        "/api/v1/location/aimags",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def aimags(self, **kwargs):
        """GET /api/v1/location/aimags – list aimags for dropdown (from ingo.location.aimag)."""
        request_id = get_request_id()
        try:
            _logger.info("location.aimags called", extra={"request_id": request_id})
            env = http.request.env
            Aimag = env["ingo.location.aimag"].sudo()
            rows = Aimag.search([], order="name")
            data = [{"id": r.id, "name": r.name} for r in rows]
            return ok(data=data, request_id=request_id)
        except Exception as e:
            _logger.exception("location.aimags error: %s", e, extra={"request_id": request_id})
            return fail(message="Internal error", code="ERROR", http_status=500, request_id=request_id)

    @http.route(
        "/api/v1/location/sums",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def sums(self, aimag_id=None, **kwargs):
        """GET /api/v1/location/sums?aimag_id= – list sums for dropdown (from ingo.location.sum)."""
        request_id = get_request_id()
        try:
            _logger.info("location.sums called", extra={"request_id": request_id, "aimag_id": aimag_id})
            if aimag_id is None or aimag_id == "":
                return fail(
                    message="aimag_id is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            try:
                aimag_id = int(aimag_id)
            except (TypeError, ValueError):
                return fail(
                    message="aimag_id must be an integer",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            env = http.request.env
            Sum = env["ingo.location.sum"].sudo()
            rows = Sum.search([("aimag_id", "=", aimag_id)], order="name")
            data = [{"id": r.id, "name": r.name} for r in rows]
            return ok(data=data, request_id=request_id)
        except Exception as e:
            _logger.exception("location.sums error: %s", e, extra={"request_id": request_id})
            return fail(message="Internal error", code="ERROR", http_status=500, request_id=request_id)

    # --- MXM routes (same data as location/aimags, location/sums; warehouses from DB) ---

    @http.route(
        "/api/v1/mxm/aimags",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def mxm_aimags(self, **kwargs):
        """GET /api/v1/mxm/aimags – list aimags (from ingo.location.aimag)."""
        return self.aimags(**kwargs)

    @http.route(
        "/api/v1/mxm/soums",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def mxm_soums(self, aimag_id=None, **kwargs):
        """GET /api/v1/mxm/soums?aimag_id= – list sums for aimag (from ingo.location.sum)."""
        return self.sums(aimag_id=aimag_id, **kwargs)

    @http.route(
        "/api/v1/mxm/warehouses",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def mxm_warehouses(self, soum_id=None, **kwargs):
        """GET /api/v1/mxm/warehouses?soum_id= – list warehouses for sum (from stock.warehouse)."""
        request_id = get_request_id()
        try:
            _logger.info(
                "mxm.warehouses called",
                extra={"request_id": request_id, "soum_id": soum_id},
            )
            if soum_id is None or soum_id == "":
                return fail(
                    message="soum_id is required",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            try:
                soum_id = int(soum_id)
            except (TypeError, ValueError):
                return fail(
                    message="soum_id must be an integer",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            env = http.request.env
            Warehouse = env["stock.warehouse"].sudo()
            rows = Warehouse.search([("x_sum_id", "=", soum_id)], order="name")
            data = [{"id": r.id, "name": r.name, "code": r.code} for r in rows]
            return ok(data=data, request_id=request_id)
        except Exception as e:
            _logger.exception(
                "mxm.warehouses error: %s",
                e,
                extra={"request_id": request_id},
            )
            return fail(message="Internal error", code="ERROR", http_status=500, request_id=request_id)
