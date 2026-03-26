# -*- coding: utf-8 -*-
"""Link POS config to warehouse (branch) for loan context."""
from odoo import fields, models


class PosConfig(models.Model):
    _inherit = "pos.config"

    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Салбар (Агуулах)",
        help="Энэ POS-ийн салбар (зээлийн контекст)",
        ondelete="restrict",
    )
