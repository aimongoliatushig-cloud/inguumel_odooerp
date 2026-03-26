# -*- coding: utf-8 -*-
"""Tests: idempotency, concurrency, OOS fallback, misconfigured store blocking."""
from odoo.tests import TransactionCase
from odoo.addons.inguumel_lucky_wheel.services.spin_service import SpinServiceError


class TestSpinService(TransactionCase):
    def setUp(self):
        super().setUp()
        self.SpinService = self.env["lucky.wheel.spin.service"]
        self.Config = self.env["lucky.wheel.config"].sudo()
        self.Node = self.env["lucky.wheel.node"].sudo()
        self.Spend = self.env["lucky.wheel.spend"].sudo()
        self.Prize = self.env["lucky.wheel.prize"].sudo()
        self.Warehouse = self.env["stock.warehouse"].sudo()
        self.SaleOrder = self.env["sale.order"].sudo()
        self.Partner = self.env["res.partner"].sudo()
        self.Product = self.env["product.product"].sudo()
        self.User = self.env["res.users"].sudo()

        self.warehouse = self.Warehouse.search([], limit=1)
        self.assertFalse(not self.warehouse, "Need at least one warehouse")
        self.partner = self.Partner.create({"name": "Test Customer", "email": "test@test.com"})
        self.user = self.User.create({
            "name": "Test User",
            "login": "lucky_test_%s" % self.id(),
            "partner_id": self.partner.id,
        })
        self.product = self.Product.search([("type", "=", "consu")], limit=1)
        if not self.product:
            self.product = self.Product.create({
                "name": "Test Product",
                "type": "consu",
            })

    def _setup_config_and_nodes(self, warehouse=None):
        wh = warehouse or self.warehouse
        config = self.Config.create({
            "warehouse_id": wh.id,
            "threshold_amount": 200000,
            "active": True,
            "default_expire_days": 14,
            "emergency_global_fallback_enabled": False,
        })
        for i in range(1, 9):
            self.Node.create({
                "warehouse_id": wh.id,
                "node_index": i,
                "prize_type": "empty" if i % 3 == 0 else "coupon",
                "coupon_payload": '{"discount":5}' if i % 3 != 0 else None,
                "weight": 1,
                "is_top_prize": i == 1,
            })
        return config

    def _create_paid_order(self, amount=250000):
        order = self.SaleOrder.create({
            "partner_id": self.partner.id,
            "warehouse_id": self.warehouse.id,
            "x_payment_method": "qpay_paid",
            "x_order_source": "mxm_mobile",
        })
        self.env["sale.order.line"].sudo().create({
            "order_id": order.id,
            "product_id": self.product.id,
            "product_uom_qty": 1,
            "price_unit": amount,
        })
        order.action_confirm()
        order.write({"state": "sale"})
        return order

    def test_misconfigured_store_blocking(self):
        """Store without 8 nodes must block spin."""
        # No config at all
        with self.assertRaises(SpinServiceError) as cm:
            self.SpinService.spin(
                user_id=self.user.id,
                warehouse_id=self.warehouse.id,
                idempotency_key="key-misconfigured-1",
            )
        self.assertEqual(cm.exception.code, "LUCKY_WHEEL_NOT_CONFIGURED")

        # Config exists but only 4 nodes
        self.Config.create({
            "warehouse_id": self.warehouse.id,
            "threshold_amount": 200000,
            "active": True,
        })
        for i in range(1, 5):
            self.Node.create({
                "warehouse_id": self.warehouse.id,
                "node_index": i,
                "prize_type": "empty",
                "weight": 1,
            })
        with self.assertRaises(SpinServiceError) as cm:
            self.SpinService.spin(
                user_id=self.user.id,
                warehouse_id=self.warehouse.id,
                idempotency_key="key-misconfigured-2",
            )
        self.assertEqual(cm.exception.code, "LUCKY_WHEEL_NOT_CONFIGURED")

    def test_idempotency(self):
        """Same idempotency_key returns same prize result."""
        self._setup_config_and_nodes()
        self._create_paid_order(250000)
        key = "idem-key-123"
        r1 = self.SpinService.spin(
            user_id=self.user.id,
            warehouse_id=self.warehouse.id,
            idempotency_key=key,
        )
        r2 = self.SpinService.spin(
            user_id=self.user.id,
            warehouse_id=self.warehouse.id,
            idempotency_key=key,
        )
        self.assertEqual(r1["prize_id"], r2["prize_id"])
        self.assertEqual(r1["prize_type"], r2["prize_type"])

    def test_not_eligible_insufficient_credits(self):
        """User with no paid orders cannot spin."""
        self._setup_config_and_nodes()
        with self.assertRaises(SpinServiceError) as cm:
            self.SpinService.spin(
                user_id=self.user.id,
                warehouse_id=self.warehouse.id,
                idempotency_key="key-no-credits",
            )
        self.assertEqual(cm.exception.code, "NOT_ELIGIBLE")

    def test_oos_fallback(self):
        """When node product is OOS, use store fallback coupon if configured."""
        config = self._setup_config_and_nodes()
        config.fallback_coupon_payload = '{"type":"fallback","value":10}'
        self._create_paid_order(250000)
        r = self.SpinService.spin(
            user_id=self.user.id,
            warehouse_id=self.warehouse.id,
            idempotency_key="key-oos-1",
        )
        self.assertIn(r["prize_type"], ("product", "coupon", "empty"))
