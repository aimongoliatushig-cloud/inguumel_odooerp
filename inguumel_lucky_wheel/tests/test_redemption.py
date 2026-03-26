# -*- coding: utf-8 -*-
"""Tests: OTP redemption."""
from odoo.tests import TransactionCase


class TestRedemption(TransactionCase):
    def setUp(self):
        super().setUp()
        self.Prize = self.env["lucky.wheel.prize"].sudo()
        self.Partner = self.env["res.partner"].sudo()
        self.User = self.env["res.users"].sudo()
        self.Warehouse = self.env["stock.warehouse"].sudo()

        self.warehouse = self.Warehouse.search([], limit=1)
        self.partner = self.Partner.create({"name": "Redeem Test", "email": "redeem@test.com"})
        self.product = self.env["product.product"].sudo().search([("type", "=", "consu")], limit=1)
        if not self.product:
            self.product = self.env["product.product"].sudo().create({"name": "Redeem Product", "type": "consu"})
        self.user = self.User.create({
            "name": "Redeem User",
            "login": "redeem_user_%s" % self.id(),
            "partner_id": self.partner.id,
        })

    def test_otp_verify(self):
        """OTP generation and verification."""
        prize = self.Prize.create({
            "user_id": self.user.id,
            "warehouse_id": self.warehouse.id,
            "prize_type": "coupon",
            "coupon_payload": "{}",
            "state": "won",
        })
        otp = prize._generate_and_store_otp()
        self.assertEqual(len(otp), 6)
        self.assertTrue(otp.isdigit())
        self.assertTrue(prize.verify_otp(otp))
        self.assertFalse(prize.verify_otp("000000"))
        self.assertFalse(prize.verify_otp(""))
