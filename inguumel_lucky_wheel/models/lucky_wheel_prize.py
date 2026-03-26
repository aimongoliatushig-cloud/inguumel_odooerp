# -*- coding: utf-8 -*-
"""
Lucky Wheel prize (won by user).
"""
from odoo import api, fields, models

import hashlib
import secrets


def _hash_otp(otp: str, salt: str) -> str:
    return hashlib.sha256((str(otp) + salt).encode()).hexdigest()


def _generate_otp() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(6))


class LuckyWheelPrize(models.Model):
    _name = "lucky.wheel.prize"
    _description = "Lucky Wheel Prize"
    _order = "won_at desc"

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
    )
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Warehouse",
        required=True,
        ondelete="cascade",
        index=True,
    )
    prize_type = fields.Selection(
        [
            ("product", "Product"),
            ("coupon", "Coupon"),
            ("empty", "Empty"),
        ],
        string="Prize Type",
        required=True,
    )
    product_id = fields.Many2one("product.product", string="Product")
    coupon_payload = fields.Char(string="Coupon Payload")
    state = fields.Selection(
        [
            ("won", "Won"),
            ("pending", "Pending"),
            ("redeemed", "Redeemed"),
            ("expired", "Expired"),
        ],
        string="State",
        required=True,
        default="won",
        index=True,
    )
    idempotency_key = fields.Char(
        string="Idempotency Key",
        index=True,
        help="Unique per user+warehouse for spin deduplication.",
    )
    otp_code_hash = fields.Char(
        string="OTP Hash",
        help="SHA256 hash of OTP for redemption verification.",
    )
    otp_salt = fields.Char(string="OTP Salt")
    won_at = fields.Datetime(string="Won At", default=fields.Datetime.now)
    expires_at = fields.Datetime(string="Expires At")
    redeemed_at = fields.Datetime(string="Redeemed At")
    redeemed_by_user_id = fields.Many2one("res.users", string="Redeemed By")
    redeem_channel = fields.Selection(
        [
            ("pos", "POS / In-Store"),
            ("delivery", "Delivery Driver"),
            ("admin", "Admin"),
        ],
        string="Redeem Channel",
    )
    node_index = fields.Integer(string="Node Index", help="Wheel node that produced this prize.")
    is_top_prize = fields.Boolean(string="Is Top Prize", default=False)
    stock_move_id = fields.Many2one(
        "stock.move",
        string="Stock Move",
        readonly=True,
        help="Outgoing stock move when prize_type=product and redeemed.",
    )

    _sql_constraints = [
        (
            "idempotency_key_user_wh_unique",
            "UNIQUE(user_id, warehouse_id, idempotency_key)",
            "Idempotency key must be unique per user per warehouse.",
        ),
    ]

    def _generate_and_store_otp(self):
        """Generate 6-digit OTP, store hash, return plain OTP (only on create)."""
        self.ensure_one()
        otp = _generate_otp()
        salt = secrets.token_hex(16)
        self.otp_code_hash = _hash_otp(otp, salt)
        self.otp_salt = salt
        return otp

    def verify_otp(self, otp: str) -> bool:
        """Verify given OTP against stored hash."""
        self.ensure_one()
        if not self.otp_salt or not self.otp_code_hash:
            return False
        h = _hash_otp(str(otp).strip(), self.otp_salt)
        return h == self.otp_code_hash

    def _cron_expire_prizes(self):
        """Cron: mark prizes expired when expires_at < now and state in (won, pending)."""
        self.env.cr.execute("""
            UPDATE lucky_wheel_prize
            SET state = 'expired'
            WHERE state IN ('won', 'pending')
              AND expires_at IS NOT NULL
              AND expires_at < NOW() AT TIME ZONE 'UTC'
        """)

    def _create_stock_move_for_product(self, warehouse):
        """Create outgoing stock move 0 amount. Returns stock.move."""
        self.ensure_one()
        if self.prize_type != "product" or not self.product_id:
            return self.env["stock.move"]
        if self.stock_move_id:
            return self.stock_move_id
        Move = self.env["stock.move"].sudo()
        picking_type = warehouse.out_type_id
        if not picking_type:
            return self.env["stock.move"]
        src = warehouse.lot_stock_id
        dest = self.env["stock.location"].search(
            [("usage", "=", "customer"), ("company_id", "in", (False, warehouse.company_id.id))],
            limit=1,
        )
        if not src or not dest:
            return self.env["stock.move"]
        vals = {
            "name": "Lucky Wheel Prize #%s" % self.id,
            "origin": "Lucky Wheel Prize %s" % self.id,
            "product_id": self.product_id.id,
            "product_uom_qty": 1.0,
            "product_uom": self.product_id.uom_id.id,
            "location_id": src.id,
            "location_dest_id": dest.id,
            "picking_type_id": picking_type.id,
            "price_unit": 0.0,
        }
        move = Move.create(vals)
        move._action_confirm()
        move._action_assign()
        if move.state in ("assigned", "confirmed", "waiting"):
            move._set_quantity_done(1.0)
            move._action_done()
        self.stock_move_id = move.id
        return move
