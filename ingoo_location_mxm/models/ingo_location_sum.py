# -*- coding: utf-8 -*-
"""Sum (district) model for MXM location hierarchy."""
from odoo import fields, models


class IngoLocationSum(models.Model):
    _name = "ingo.location.sum"
    _description = "Sum (District)"

    name = fields.Char(string="Name", required=True, index=True)
    aimag_id = fields.Many2one(
        "ingo.location.aimag",
        string="Aimag",
        required=True,
        ondelete="cascade",
        index=True,
    )
