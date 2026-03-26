# -*- coding: utf-8 -*-
"""
Credit API: loan list, loan get, register repayment.
All message fields in responses are Mongolian (MN only).
Try/except on every route; request_id in logs and response.
"""
import json
import logging

from odoo import http
from odoo.addons.inguumel_mobile_api.controllers.base import (
    get_request_id,
    ok,
    fail_payload,
)

_logger = logging.getLogger(__name__)

# Kill-switch key for this API (ir.config_parameter)
CREDIT_API_DISABLED_KEY = "api_disabled:/api/v1/credit"


def _parse_json_body(request, request_id):
    """Parse JSON body; return (data_dict, error_response or None)."""
    if hasattr(request, "jsonrequest") and request.jsonrequest is not None:
        data = request.jsonrequest if isinstance(request.jsonrequest, dict) else {}
        return data, None
    ct = (request.httprequest.content_type or "").strip().lower()
    if "application/json" not in ct:
        return None, fail_payload(
            message="JSON биш",
            code="INVALID_JSON",
            http_status=400,
            request_id=request_id,
        )
    raw = request.httprequest.get_data(as_text=True)
    if not raw or not raw.strip():
        return None, fail_payload(
            message="JSON биш",
            code="INVALID_JSON",
            http_status=400,
            request_id=request_id,
        )
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None, fail_payload(
            message="JSON буруу",
            code="INVALID_JSON",
            http_status=400,
            request_id=request_id,
        )
    if not isinstance(data, dict):
        return None, fail_payload(
            message="JSON биш",
            code="INVALID_JSON",
            http_status=400,
            request_id=request_id,
        )
    return data, None


def _check_kill_switch(env, request_id):
    """If API disabled, return 503 response; else None."""
    try:
        ICP = env["ir.config_parameter"].sudo()
        if ICP.get_param(CREDIT_API_DISABLED_KEY) in ("1", "true", "True"):
            return fail_payload(
                message="Зээлийн API түр идэвхгүй",
                code="SERVICE_UNAVAILABLE",
                http_status=503,
                request_id=request_id,
            )
    except Exception:
        pass
    return None


def _loan_to_dict(loan):
    """Serialize one loan for API (no binary). State label in Mongolian."""
    state_labels = {
        "open": "Нээлттэй",
        "partial": "Хэсэгчлэн төлөгдсөн",
        "paid": "Бүрэн төлөгдсөн",
        "cancelled": "Цуцлагдсан",
    }
    return {
        "id": loan.id,
        "name": loan.name,
        "warehouse_id": loan.warehouse_id.id,
        "partner_id": loan.partner_id.id,
        "amount_total": loan.amount_total,
        "amount_paid": loan.amount_paid,
        "amount_residual": loan.amount_residual,
        "date_due": str(loan.date_due) if loan.date_due else None,
        "state": loan.state,
        "state_label": state_labels.get(loan.state, loan.state),
        "is_overdue": loan.is_overdue,
    }


class CreditAPI(http.Controller):
    """Credit endpoints: list loans, get loan, register repayment. Messages in Mongolian."""

    @http.route(
        "/api/v1/credit/loans",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def loans_list(self, **kwargs):
        """GET /api/v1/credit/loans?warehouse_id=&partner_id=&limit=50&offset=0"""
        request_id = get_request_id()
        try:
            _logger.info("credit.loans_list called", extra={"request_id": request_id})
            env = http.request.env
            err = _check_kill_switch(env, request_id)
            if err is not None:
                return err
            limit = kwargs.get("limit", "50")
            offset = kwargs.get("offset", "0")
            try:
                limit = min(50, max(1, int(limit)))
            except (TypeError, ValueError):
                limit = 50
            try:
                offset = max(0, int(offset))
            except (TypeError, ValueError):
                offset = 0
            warehouse_id = kwargs.get("warehouse_id")
            partner_id = kwargs.get("partner_id")
            if warehouse_id is not None:
                try:
                    warehouse_id = int(warehouse_id)
                except (TypeError, ValueError):
                    warehouse_id = None
            if partner_id is not None:
                try:
                    partner_id = int(partner_id)
                except (TypeError, ValueError):
                    partner_id = None
            svc = env["inguumel.credit.loan.service"]
            loans = svc.loan_list(
                warehouse_id=warehouse_id,
                partner_id=partner_id,
                limit=limit,
                offset=offset,
            )
            data = [_loan_to_dict(l) for l in loans]
            return ok(
                data=data,
                message="Амжилттай",
                code="OK",
                meta={"count": len(data), "limit": limit, "offset": offset},
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "credit.loans_list error: %s", e, extra={"request_id": request_id}
            )
            return fail_payload(
                message="Сервер дотор алдаа гарлаа",
                code="ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/credit/loans/<int:loan_id>",
        type="http",
        auth="user",
        methods=["GET"],
        csrf=False,
    )
    def loan_get(self, loan_id, **kwargs):
        """GET /api/v1/credit/loans/<id>"""
        request_id = get_request_id()
        try:
            _logger.info(
                "credit.loan_get called",
                extra={"request_id": request_id, "loan_id": loan_id},
            )
            env = http.request.env
            err = _check_kill_switch(env, request_id)
            if err is not None:
                return err
            svc = env["inguumel.credit.loan.service"]
            loan = svc.loan_get(loan_id)
            if not loan:
                return fail_payload(
                    message="Зээл олдсонгүй",
                    code="NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            return ok(
                data=_loan_to_dict(loan),
                message="Амжилттай",
                code="OK",
                request_id=request_id,
            )
        except Exception as e:
            _logger.exception(
                "credit.loan_get error: %s", e, extra={"request_id": request_id}
            )
            return fail_payload(
                message="Сервер дотор алдаа гарлаа",
                code="ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/credit/repayments",
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def repayment_register(self, **kwargs):
        """POST /api/v1/credit/repayments – JSON { loan_id, amount [, date, notes ] }"""
        request_id = get_request_id()
        try:
            _logger.info(
                "credit.repayment_register called", extra={"request_id": request_id}
            )
            env = http.request.env
            err = _check_kill_switch(env, request_id)
            if err is not None:
                return err
            payload, err = _parse_json_body(http.request, request_id)
            if err is not None:
                return err
            payload = payload or {}
            loan_id = payload.get("loan_id")
            amount = payload.get("amount")
            if loan_id is None:
                return fail_payload(
                    message="Зээлийн дугаар заавал оруулна уу",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            if amount is None:
                return fail_payload(
                    message="Төлөх дүн заавал оруулна уу",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                return fail_payload(
                    message="Төлөх дүн буруу байна",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            if amount <= 0 or amount > 999999999:
                return fail_payload(
                    message="Төлөх дүн заавал оруулна уу",
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            date = payload.get("date")
            notes = payload.get("notes") or ""
            if not isinstance(notes, str):
                notes = str(notes)
            svc = env["inguumel.credit.loan.service"]
            repayment = svc.repayment_register(
                loan_id=loan_id,
                amount=amount,
                date=date,
                notes=notes,
                source="api",
            )
            return ok(
                data={
                    "id": repayment.id,
                    "loan_id": repayment.loan_id.id,
                    "amount": repayment.amount,
                    "date": str(repayment.date),
                },
                message="Зээлийн төлөлт амжилттай бүртгэгдлээ",
                code="OK",
                request_id=request_id,
            )
        except Exception as e:
            from odoo.exceptions import ValidationError
            if isinstance(e, ValidationError):
                _logger.warning(
                    "credit.repayment_register validation: %s",
                    e,
                    extra={"request_id": request_id},
                )
                return fail_payload(
                    message=str(e),
                    code="VALIDATION_ERROR",
                    http_status=400,
                    request_id=request_id,
                )
            _logger.exception(
                "credit.repayment_register error: %s",
                e,
                extra={"request_id": request_id},
            )
            return fail_payload(
                message="Сервер дотор алдаа гарлаа",
                code="ERROR",
                http_status=500,
                request_id=request_id,
            )
