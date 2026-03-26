# -*- coding: utf-8 -*-
"""Extend res.users: x_warehouse_ids for Warehouse Owner scoped access (mobile order/delivery)."""
from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    x_warehouse_ids = fields.Many2many(
        "stock.warehouse",
        "res_users_stock_warehouse_rel",
        "user_id",
        "warehouse_id",
        string="Assigned Warehouses (Warehouse Owner)",
        help="When set, user has warehouse-scoped access: sees/updates only orders belonging to these warehouses (mobile API).",
    )
