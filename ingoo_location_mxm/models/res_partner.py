# -*- coding: utf-8 -*-
"""Extend res.partner: aimag and sum (Many2one to location models)."""
from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    x_aimag_id = fields.Many2one(
        "ingo.location.aimag",
        string="Aimag",
        ondelete="set null",
        index=True,
    )
    x_sum_id = fields.Many2one(
        "ingo.location.sum",
        string="Sum",
        ondelete="set null",
        index=True,
        domain="[('aimag_id', '=', x_aimag_id)]",
    )
