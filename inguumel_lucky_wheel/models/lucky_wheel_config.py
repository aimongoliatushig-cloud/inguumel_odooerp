# -*- coding: utf-8 -*-
"""
Lucky Wheel config per warehouse.
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LuckyWheelConfig(models.Model):
    _name = "lucky.wheel.config"
    _description = "Lucky Wheel Configuration"
    _rec_name = "warehouse_id"

    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Warehouse",
        required=True,
        ondelete="cascade",
        index=True,
    )
    threshold_amount = fields.Float(
        string="Threshold Amount (₮)",
        default=200000.0,
        required=True,
        help="Accumulated paid amount needed per 1 spin.",
    )
    active = fields.Boolean(string="Active", default=True)
    default_expire_days = fields.Integer(
        string="Default Prize Expire (Days)",
        default=14,
        required=True,
        help="Days until unredeemed prize expires.",
    )
    emergency_global_fallback_enabled = fields.Boolean(
        string="Emergency Global Fallback",
        default=False,
        help="If True, use admin-configured global fallback when node prize OOS and no store fallback.",
    )
    top_prize_cooldown_days = fields.Integer(
        string="Top Prize Cooldown (Days)",
        default=30,
        help="Minimum days between top prizes per user per warehouse (0 = no cooldown).",
    )
    fallback_product_id = fields.Many2one(
        "product.product",
        string="Store Fallback Product",
        help="Used when selected node product is out of stock.",
    )
    fallback_coupon_payload = fields.Char(
        string="Store Fallback Coupon",
        help="JSON string for fallback coupon when product OOS.",
    )

    _sql_constraints = [
        ("warehouse_unique", "UNIQUE(warehouse_id)", "One config per warehouse."),
    ]

    @api.constrains("threshold_amount", "default_expire_days", "top_prize_cooldown_days")
    def _check_positive(self):
        for rec in self:
            if rec.threshold_amount <= 0:
                raise ValidationError("Threshold amount must be positive.")
            if rec.default_expire_days < 0:
                raise ValidationError("Default expire days cannot be negative.")
            if rec.top_prize_cooldown_days < 0:
                raise ValidationError("Top prize cooldown days cannot be negative.")
