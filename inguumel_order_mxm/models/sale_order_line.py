# -*- coding: utf-8 -*-
"""
MXM API orders: force warehouse delivery route in procurement values; pass MXM context
into _action_launch_stock_rule so stock.rule._get_rule can block Transit/MTO.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    def _prepare_procurement_values(self, group_id=False):
        values = super()._prepare_procurement_values()
        self.ensure_one()
        order = self.order_id
        if order.x_order_source in ("mxm_mobile", "mxm_cart") and order.warehouse_id:
            wh = order.warehouse_id
            route = (
                wh.delivery_route_id
                if wh.delivery_route_id and wh.delivery_route_id.exists()
                else self.env["stock.route"].sudo().browse(3)
            )
            if route and route.exists():
                values["route_ids"] = route
                values["warehouse_id"] = wh
                values["mxm_force_route_id"] = route.id
        return values

    def _action_launch_stock_rule(self, *, previous_product_uom_qty=False):
        mxm_lines = self.filtered(lambda l: l.order_id.x_order_source in ("mxm_mobile", "mxm_cart"))
        if mxm_lines:
            order = mxm_lines[0].order_id
            wh = order.warehouse_id
            route = (
                wh.delivery_route_id
                if wh and wh.delivery_route_id and wh.delivery_route_id.exists()
                else self.env["stock.route"].sudo().browse(3)
            )
            route_id = route.id if route and route.exists() else 3
            for line in mxm_lines:
                _logger.info(
                    "[MXM_LAUNCH_STOCK_RULE] order=%s(%s) wh=%s line=%s prod=%s type=%s line_routes=%s",
                    order.name or "",
                    order.id,
                    wh.id if wh else None,
                    line.id,
                    line.product_id.id if line.product_id else None,
                    getattr(line.product_id, "type", None) if line.product_id else None,
                    line.route_ids.ids if line.route_ids else [],
                )
            self = self.with_context(
                disable_mto=True,
                force_warehouse_id=wh.id if wh else None,
                warehouse_id=wh.id if wh else None,
                mxm_force_route_id=route_id,
                mxm_block_transit=True,
            )
        return super()._action_launch_stock_rule(previous_product_uom_qty=previous_product_uom_qty)
