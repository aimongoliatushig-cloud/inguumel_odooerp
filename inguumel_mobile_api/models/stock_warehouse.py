# -*- coding: utf-8 -*-
"""
Extend stock.warehouse: aimag/sum for location resolution.

Uses Many2one to ingo.location.aimag and ingo.location.sum so the UI shows
relational dropdowns. API contracts are unchanged: x_sum_id is still compared
by record ID (e.g. search [("x_sum_id", "=", sum_id)] works with sum record id).
"""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StockWarehouse(models.Model):
    _inherit = "stock.warehouse"

    x_aimag_id = fields.Many2one(
        "ingo.location.aimag",
        string="Aimag",
        ondelete="restrict",
        index=True,
    )
    x_sum_id = fields.Many2one(
        "ingo.location.sum",
        string="Sum",
        ondelete="restrict",
        index=True,
        domain="[('aimag_id', '=', x_aimag_id)]",
    )

    _sql_constraints = [
        (
            "stock_warehouse_x_sum_id_unique",
            "UNIQUE(x_sum_id)",
            "This sum already has a warehouse.",
        ),
    ]

    @api.constrains("x_sum_id", "x_aimag_id")
    def _check_sum_belongs_to_aimag(self):
        """Sum must belong to the selected Aimag."""
        for rec in self:
            if not rec.x_sum_id or not rec.x_aimag_id:
                continue
            if rec.x_sum_id.aimag_id != rec.x_aimag_id:
                raise ValidationError(
                    _("The selected Sum must belong to the selected Aimag.")
                )

    @api.constrains("x_sum_id")
    def _check_sum_unique_per_warehouse(self):
        """Enforce one sum → one warehouse. Same sum cannot be used by another warehouse."""
        for rec in self:
            if not rec.x_sum_id:
                continue
            other = self.search(
                [
                    ("x_sum_id", "=", rec.x_sum_id.id),
                    ("id", "!=", rec.id),
                ],
                limit=1,
            )
            if other:
                raise ValidationError(_("This sum already has a warehouse."))


# Migration: Integer → Many2one is handled by hooks.py (install) and
# migrations/1.0.2/pre-* and post-* (upgrade). 0 → NULL in post-migrate.
