# -*- coding: utf-8 -*-
"""API access token for Bearer auth (mobile). One token per login; used to set session.uid."""
import uuid
from odoo import api, fields, models


class ApiAccessToken(models.Model):
    _name = "api.access.token"
    _description = "API Access Token (Bearer)"

    token = fields.Char(required=True, index=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    create_date = fields.Datetime(readonly=True)

    _sql_constraints = [
        ("token_unique", "UNIQUE(token)", "Token must be unique."),
    ]

    @api.model
    def create_token(self, user_id):
        token = str(uuid.uuid4())
        self.create({"token": token, "user_id": user_id})
        return token

    @api.model
    def get_user_id_by_token(self, token):
        if not token or not isinstance(token, str):
            return None
        token = token.strip()
        if not token:
            return None
        rec = self.sudo().search([("token", "=", token)], limit=1)
        return rec.user_id.id if rec else None
