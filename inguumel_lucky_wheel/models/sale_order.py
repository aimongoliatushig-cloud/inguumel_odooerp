# -*- coding: utf-8 -*-
"""
Lucky Wheel: recompute spend when sale order changes.
"""
from odoo import models


class SaleOrderLuckyWheel(models.Model):
    _inherit = "sale.order"

    def write(self, vals):
        trigger_fields = {
            "state", "partner_id", "warehouse_id",
            "x_payment_method", "mxm_delivery_status",
            "payment_state", "x_paid", "x_cod_auto_paid",
        }
        affected_partners = set()
        if trigger_fields.intersection(vals.keys()):
            for order in self:
                if order.partner_id:
                    affected_partners.add(order.partner_id.id)
        result = super().write(vals)
        if affected_partners:
            for order in self:
                if order.partner_id:
                    affected_partners.add(order.partner_id.id)
            Spend = self.env["lucky.wheel.spend"].sudo()
            for pid in affected_partners:
                spends = Spend.search([("partner_id", "=", pid)])
                if spends:
                    spends._recompute_accumulated()
        return result
