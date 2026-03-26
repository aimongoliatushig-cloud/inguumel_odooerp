# -*- coding: utf-8 -*-
"""
Lucky Wheel spend accumulation per user + warehouse.
Only DELIVERED + PAID orders count.
"""
import logging
import math

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

PAID_METHODS = ("qpay_paid", "card_paid", "wallet_paid")


class LuckyWheelSpend(models.Model):
    _name = "lucky.wheel.spend"
    _description = "Lucky Wheel Spend"
    _rec_name = "display_name"

    user_id = fields.Many2one(
        "res.users",
        string="User",
        required=True,
        ondelete="cascade",
        index=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Partner",
        related="user_id.partner_id",
        store=True,
        index=True,
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Warehouse",
        required=True,
        ondelete="cascade",
        index=True,
    )
    accumulated_paid_amount = fields.Float(
        string="Accumulated Paid Amount",
        default=0.0,
        help="Sum of amount_total from paid orders (excl. cancelled).",
    )
    spins_consumed = fields.Integer(
        string="Spins Consumed",
        default=0,
        help="Number of spins used (prizes won).",
    )
    computed_spin_credits = fields.Integer(
        string="Spin Credits",
        compute="_compute_spin_credits",
        store=True,
    )

    display_name = fields.Char(compute="_compute_display_name", store=True)

    _sql_constraints = [
        ("user_warehouse_unique", "UNIQUE(user_id, warehouse_id)", "One spend record per user per warehouse."),
    ]

    @api.depends("user_id", "warehouse_id")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "{} @ {}".format(
                rec.user_id.name or rec.partner_id.name or "?",
                rec.warehouse_id.name or "?",
            )

    @api.depends("accumulated_paid_amount", "spins_consumed", "warehouse_id")
    def _compute_spin_credits(self):
        for rec in self:
            config = rec.warehouse_id and self.env["lucky.wheel.config"].search(
                [("warehouse_id", "=", rec.warehouse_id.id), ("active", "=", True)],
                limit=1,
            )
            if not config or config.threshold_amount <= 0:
                rec.computed_spin_credits = 0
                continue
            eligible = math.floor(rec.accumulated_paid_amount / config.threshold_amount)
            rec.computed_spin_credits = max(0, int(eligible) - rec.spins_consumed)

    def _is_order_delivered(self, order):
        """True if order is delivered (mxm_delivery_status or all outgoing pickings done)."""
        order = order.sudo()
        if hasattr(order, "mxm_delivery_status") and order.mxm_delivery_status == "delivered":
            return True
        if hasattr(order, "delivery_state") and getattr(order, "delivery_state") == "delivered":
            return True
        pickings = order.picking_ids
        if pickings:
            outgoing = pickings.filtered(
                lambda p: p.picking_type_id and getattr(p.picking_type_id, "code", None) == "outgoing"
            )
            if outgoing:
                return all(p.state == "done" for p in outgoing)
            return all(p.state == "done" for p in pickings)
        return False

    def _is_order_paid(self, order):
        """True if payment is confirmed (payment_state, x_payment_method, or x_paid)."""
        order = order.sudo()
        if hasattr(order, "payment_state") and getattr(order, "payment_state") == "paid":
            return True
        if hasattr(order, "x_payment_method") and getattr(order, "x_payment_method") in PAID_METHODS:
            return True
        if hasattr(order, "x_paid") and getattr(order, "x_paid"):
            return True
        return False

    def _order_matches_warehouse(self, order, target_warehouse_id):
        """True if order belongs to target warehouse (from order.warehouse_id or done outgoing pickings).
        Returns (matches: bool, resolved_warehouse_id: int|None).
        """
        order = order.sudo()
        if order.warehouse_id and order.warehouse_id.id == target_warehouse_id:
            return True, order.warehouse_id.id
        outgoing = order.picking_ids.filtered(
            lambda p: p.picking_type_id
            and getattr(p.picking_type_id, "code", None) == "outgoing"
            and p.state == "done"
        )
        for p in outgoing:
            if p.picking_type_id.warehouse_id and p.picking_type_id.warehouse_id.id == target_warehouse_id:
                return True, p.picking_type_id.warehouse_id.id
        resolved = order.warehouse_id.id if order.warehouse_id else None
        if not resolved and outgoing:
            resolved = outgoing[0].picking_type_id.warehouse_id.id if outgoing[0].picking_type_id.warehouse_id else None
        return False, resolved

    def _recompute_accumulated(self):
        """Recompute from DELIVERED + PAID orders only. Warehouse from order or from done outgoing pickings."""
        SaleOrder = self.env["sale.order"].sudo()
        for rec in self:
            if not rec.partner_id or not rec.warehouse_id:
                rec.accumulated_paid_amount = 0.0
                _logger.info("[LuckyWheel] recompute user=%s SKIP partner or warehouse missing", rec.user_id.id)
                continue
            target_wh_id = rec.warehouse_id.id
            domain = [
                ("partner_id", "=", rec.partner_id.id),
                ("state", "in", ("sale", "done")),
            ]
            orders = SaleOrder.search(domain)
            total = 0.0
            matched_ids = []
            for order in orders:
                matches_wh, resolved_wh = rec._order_matches_warehouse(order, target_wh_id)
                if not matches_wh:
                    _logger.info(
                        "[LuckyWheel] order=%s id=%s resolved_wh=%s amount=%s SKIP warehouse_mismatch",
                        order.name,
                        order.id,
                        resolved_wh,
                        order.amount_total,
                    )
                    continue
                if not rec._is_order_delivered(order):
                    _logger.info(
                        "[LuckyWheel] order=%s id=%s resolved_wh=%s amount=%s SKIP not_delivered",
                        order.name,
                        order.id,
                        resolved_wh,
                        order.amount_total,
                    )
                    continue
                if not rec._is_order_paid(order):
                    _logger.info(
                        "[LuckyWheel] order=%s id=%s resolved_wh=%s amount=%s SKIP not_paid",
                        order.name,
                        order.id,
                        resolved_wh,
                        order.amount_total,
                    )
                    continue
                total += order.amount_total
                matched_ids.append(order.id)
                _logger.info(
                    "[LuckyWheel] order=%s id=%s resolved_wh=%s amount=%s INCLUDED",
                    order.name,
                    order.id,
                    resolved_wh,
                    order.amount_total,
                )
            rec.accumulated_paid_amount = total
            _logger.info(
                "[LuckyWheel] recompute user=%s partner=%s warehouse=%s orders=%s total=%s spins=%s",
                rec.user_id.id,
                rec.partner_id.id,
                rec.warehouse_id.id,
                matched_ids,
                total,
                rec.computed_spin_credits,
            )

    @api.model
    def _recompute_for_partner_warehouse(self, partner_id, warehouse_id):
        """Recompute accumulated for all spend records matching partner+warehouse."""
        spends = self.search([
            ("partner_id", "=", partner_id),
            ("warehouse_id", "=", warehouse_id),
        ])
        spends._recompute_accumulated()

    @api.model
    def get_or_create(self, user_id, warehouse_id):
        """Get or create spend record for user+warehouse. Returns record."""
        rec = self.search([
            ("user_id", "=", user_id),
            ("warehouse_id", "=", warehouse_id),
        ], limit=1)
        if rec:
            rec._recompute_accumulated()
            return rec
        rec = self.create({
            "user_id": user_id,
            "warehouse_id": warehouse_id,
        })
        rec._recompute_accumulated()
        return rec
