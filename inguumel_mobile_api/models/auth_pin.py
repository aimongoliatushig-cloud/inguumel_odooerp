# -*- coding: utf-8 -*-
"""
Model inguumel.auth_pin – stores hashed PIN + expiry for phone-only login.
"""
from odoo import fields, models


class InguumelAuthPin(models.Model):
    _name = "inguumel.auth_pin"
    _description = "Auth PIN Requests"
    _order = "create_date desc"

    phone = fields.Char(required=True, index=True)
    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    pin_hash = fields.Char(required=True)
    expires_at = fields.Datetime(required=True, index=True)
    attempts = fields.Integer(default=0)
    consumed = fields.Boolean(default=False, index=True)
    request_id = fields.Char(index=True)
