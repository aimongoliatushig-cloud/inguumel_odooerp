# -*- coding: utf-8 -*-
"""
Lucky Wheel node (1-8) per warehouse.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LuckyWheelNode(models.Model):
    _name = "lucky.wheel.node"
    _description = "Lucky Wheel Node"
    _order = "warehouse_id, node_index"

    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Warehouse",
        required=True,
        ondelete="cascade",
        index=True,
    )
    node_index = fields.Integer(
        string="Node Index",
        required=True,
        help="1-8, unique per warehouse.",
    )
    prize_type = fields.Selection(
        [
            ("product", "Product"),
            ("coupon", "Coupon"),
            ("empty", "Empty"),
        ],
        string="Prize Type",
        required=True,
        default="empty",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        help="Required when prize_type=product.",
    )
    coupon_payload = fields.Char(
        string="Coupon Payload",
        help="JSON string when prize_type=coupon.",
    )
    weight = fields.Integer(
        string="Weight",
        default=1,
        required=True,
        help="Higher = more likely (RNG uses weighted draw).",
    )
    is_top_prize = fields.Boolean(
        string="Is Top Prize",
        default=False,
        help="Subject to cooldown when configured.",
    )
    active = fields.Boolean(string="Active", default=True)

    _sql_constraints = [
        (
            "warehouse_node_unique",
            "UNIQUE(warehouse_id, node_index)",
            "Node index must be unique per warehouse.",
        ),
    ]

    @api.constrains("node_index")
    def _check_node_index(self):
        for rec in self:
            if not (1 <= rec.node_index <= 8):
                raise ValidationError("Node index must be between 1 and 8.")

    @api.constrains("prize_type", "product_id", "coupon_payload")
    def _check_prize_content(self):
        for rec in self:
            if rec.prize_type == "product" and not rec.product_id:
                raise ValidationError("Product is required when prize_type is product.")
            if rec.prize_type == "coupon" and not rec.coupon_payload:
                raise ValidationError("Coupon payload is required when prize_type is coupon.")
