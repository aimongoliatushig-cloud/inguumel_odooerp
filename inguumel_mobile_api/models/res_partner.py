# -*- coding: utf-8 -*-
"""Extend res.partner: default warehouse, PIN hash (x_aimag_id/x_sum_id in ingoo_location_mxm)."""
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_default_warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Default Warehouse",
        ondelete="set null",
        index=True,
    )
    x_pin_hash = fields.Char(string="PIN Hash")
    x_phone_2 = fields.Char(string="Secondary Phone")
