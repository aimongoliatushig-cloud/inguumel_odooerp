# -*- coding: utf-8 -*-
"""MXM Cart: warehouse-scoped basket per partner."""
from odoo import api, fields, models


class MxmCart(models.Model):
    _name = "mxm.cart"
    _description = "MXM Cart (warehouse-scoped basket)"

    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        required=True,
        ondelete="cascade",
        index=True,
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Warehouse",
        required=True,
        ondelete="cascade",
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Company",
        related="warehouse_id.company_id",
        store=True,
        readonly=True,
    )
    line_ids = fields.One2many(
        "mxm.cart.line",
        "cart_id",
        string="Lines",
        copy=False,
    )

    _sql_constraints = [
        (
            "mxm_cart_partner_warehouse_unique",
            "UNIQUE(partner_id, warehouse_id)",
            "One cart per partner per warehouse.",
        ),
    ]

    @api.model
    def get_or_create(self, partner_id, warehouse_id):
        """Find cart for (partner, warehouse) or create empty one."""
        cart = self.search(
            [
                ("partner_id", "=", partner_id),
                ("warehouse_id", "=", warehouse_id),
            ],
            limit=1,
        )
        if not cart:
            cart = self.create({
                "partner_id": partner_id,
                "warehouse_id": warehouse_id,
            })
        return cart
