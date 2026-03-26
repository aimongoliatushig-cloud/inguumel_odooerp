# -*- coding: utf-8 -*-
"""Tests: refund/cancel subtraction from spend."""
from odoo.tests import TransactionCase


class TestSpendAccumulation(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Spend = self.env["lucky.wheel.spend"].sudo()
        self.SaleOrder = self.env["sale.order"].sudo()
        self.Partner = self.env["res.partner"].sudo()
        self.Product = self.env["product.product"].sudo()
        self.User = self.env["res.users"].sudo()
        self.Warehouse = self.env["stock.warehouse"].sudo()

        self.warehouse = self.Warehouse.search([], limit=1)
        self.partner = self.Partner.create({"name": "Spend Test", "email": "spend@test.com"})
        self.user = self.User.create({
            "name": "Spend User",
            "login": "spend_user_%s" % self.id(),
            "partner_id": self.partner.id,
        })
        self.product = self.Product.search([("type", "=", "consu")], limit=1)
        if not self.product:
            self.product = self.Product.create({"name": "Spend Product", "type": "consu"})

    def _create_order(self, amount=250000, payment="qpay_paid"):
        order = self.SaleOrder.create({
            "partner_id": self.partner.id,
            "warehouse_id": self.warehouse.id,
            "x_payment_method": payment,
            "x_order_source": "mxm_mobile",
        })
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.product.id,
            "product_uom_qty": 1,
            "price_unit": amount,
        })
        return order

    def test_refund_cancel_subtraction(self):
        """Cancel/refund: order with state=cancel should not count in accumulated."""
        spend = self.Spend.get_or_create(self.user.id, self.warehouse.id)
        order = self._create_order(250000)
        order.action_confirm()
        order.write({"state": "sale"})
        spend._recompute_accumulated()
        self.assertGreaterEqual(spend.accumulated_paid_amount, 250000)

        order.write({"state": "cancel"})
        spend._recompute_accumulated()
        self.assertEqual(spend.accumulated_paid_amount, 0)

    def test_paid_only(self):
        """Only qpay_paid/card_paid/wallet_paid count; cod does not."""
        order = self._create_order(250000, payment="cod")
        order.action_confirm()
        order.write({"state": "sale"})
        spend = self.Spend.get_or_create(self.user.id, self.warehouse.id)
        spend._recompute_accumulated()
        self.assertEqual(spend.accumulated_paid_amount, 0)

        order.write({"x_payment_method": "qpay_paid"})
        spend._recompute_accumulated()
        self.assertGreaterEqual(spend.accumulated_paid_amount, 250000)
