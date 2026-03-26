# -*- coding: utf-8 -*-
"""MXM Cart Line: product + qty + price."""
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MxmCartLine(models.Model):
    _name = "mxm.cart.line"
    _description = "MXM Cart Line"

    cart_id = fields.Many2one(
        "mxm.cart",
        string="Cart",
        required=True,
        ondelete="cascade",
        index=True,
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True,
        ondelete="cascade",
        index=True,
    )
    product_uom_qty = fields.Float(
        string="Quantity",
        required=True,
        default=1.0,
    )
    price_unit = fields.Float(
        string="Unit Price",
        required=True,
        default=0.0,
    )

    @api.constrains("product_uom_qty")
    def _check_qty_positive(self):
        for line in self:
            if line.product_uom_qty <= 0:
                raise ValidationError(_("Quantity must be positive."))

    @api.depends("product_uom_qty", "price_unit")
    def _compute_subtotal(self):
        for line in self:
            line.price_subtotal = line.price_unit * line.product_uom_qty

    price_subtotal = fields.Float(
        string="Subtotal",
        compute="_compute_subtotal",
        store=True,
    )
