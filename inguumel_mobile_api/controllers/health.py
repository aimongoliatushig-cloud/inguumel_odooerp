# -*- coding: utf-8 -*-
"""
Lightweight health check for API observability.
GET /api/v1/health – returns { success: true, code: "OK" } with request_id.
"""
from odoo import http
from odoo.addons.inguumel_mobile_api.controllers.base import get_request_id, ok


class HealthAPI(http.Controller):
    @http.route(
        "/api/v1/health",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def health(self, **kwargs):
        """GET /api/v1/health – lightweight health check. Returns success, code, request_id."""
        request_id = get_request_id()
        return ok(data=None, message="OK", code="OK", request_id=request_id)
