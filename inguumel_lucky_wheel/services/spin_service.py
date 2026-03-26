# -*- coding: utf-8 -*-
"""
Lucky Wheel spin business logic.
"""
import logging
import math
import random

from odoo import fields, models

_logger = logging.getLogger(__name__)

KILL_SWITCH_PARAM = "api_disabled:/api/v1/lucky-wheel"
GLOBAL_FALLBACK_PRODUCT_PARAM = "lucky_wheel.global_fallback_product_id"
GLOBAL_FALLBACK_COUPON_PARAM = "lucky_wheel.global_fallback_coupon_payload"
REQUIRED_NODES = 8


class SpinServiceError(Exception):
    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


class LuckyWheelSpinService(models.AbstractModel):
    _name = "lucky.wheel.spin.service"
    _description = "Lucky Wheel Spin Service"

    def _check_kill_switch(self):
        val = self.env["ir.config_parameter"].sudo().get_param(KILL_SWITCH_PARAM, "") or ""
        if val.strip().lower() in ("1", "true", "yes"):
            raise SpinServiceError("SERVICE_UNAVAILABLE", "Lucky wheel API is disabled")

    def _resolve_warehouse(self, warehouse_id):
        wh = self.env["stock.warehouse"].sudo().browse(warehouse_id)
        if not wh.exists():
            raise SpinServiceError("VALIDATION_ERROR", "Warehouse not found")
        return wh

    def _get_config(self, warehouse):
        config = self.env["lucky.wheel.config"].sudo().search(
            [("warehouse_id", "=", warehouse.id), ("active", "=", True)],
            limit=1,
        )
        if not config:
            raise SpinServiceError("WAREHOUSE_NOT_CONFIGURED", "Lucky wheel not configured for this warehouse")
        return config

    def _get_nodes(self, warehouse):
        nodes = (
            self.env["lucky.wheel.node"]
            .sudo()
            .search(
                [
                    ("warehouse_id", "=", warehouse.id),
                    ("active", "=", True),
                    ("node_index", ">=", 1),
                    ("node_index", "<=", REQUIRED_NODES),
                ],
                order="node_index",
            )
        )
        if len(nodes) != REQUIRED_NODES:
            raise SpinServiceError(
                "WAREHOUSE_NOT_CONFIGURED",
                "Exactly %d nodes required for warehouse" % REQUIRED_NODES,
            )
        return nodes

    def _product_qty_available(self, product, warehouse):
        """Return available qty (quantity - reserved) in warehouse."""
        if not product or product.type != "product":
            return 0.0
        quants = self.env["stock.quant"].sudo().search(
            [
                ("product_id", "=", product.id),
                ("location_id", "=", warehouse.lot_stock_id.id),
            ],
        )
        return sum((q.quantity or 0) - (q.reserved_quantity or 0) for q in quants)

    def _select_node_weighted(self, nodes):
        total = sum(n.weight for n in nodes if n.weight > 0)
        if total <= 0:
            return nodes[0]
        r = random.uniform(0, total)
        acc = 0
        for n in nodes:
            acc += n.weight
            if r < acc:
                return n
        return nodes[-1]

    def _resolve_prize(self, node, config, warehouse, user):
        """
        Resolve final prize from node. If product OOS, use fallback.
        Returns (prize_type, product_id, coupon_payload, node_index).
        """
        pt = node.prize_type
        product_id = node.product_id
        coupon_payload = node.coupon_payload
        node_index = node.node_index

        if pt == "empty":
            return ("empty", False, None, node_index)
        if pt == "coupon":
            return ("coupon", False, coupon_payload or "{}", node_index)
        # product
        qty = self._product_qty_available(node.product_id, warehouse) if node.product_id else 0
        if qty > 0:
            return ("product", node.product_id.id, None, node_index)
        # OOS: try store fallback
        if config.fallback_product_id:
            qty_fb = self._product_qty_available(config.fallback_product_id, warehouse)
            if qty_fb > 0:
                return ("product", config.fallback_product_id.id, None, node_index)
        if config.fallback_coupon_payload:
            return ("coupon", False, config.fallback_coupon_payload, node_index)
        # emergency global fallback
        if not config.emergency_global_fallback_enabled:
            raise SpinServiceError(
                "PRIZE_OUT_OF_STOCK",
                "Selected prize out of stock and no fallback configured",
            )
        ICP = self.env["ir.config_parameter"].sudo()
        global_product_id = ICP.get_param(GLOBAL_FALLBACK_PRODUCT_PARAM)
        if global_product_id:
            try:
                pid = int(global_product_id)
                prod = self.env["product.product"].sudo().browse(pid)
                if prod.exists() and self._product_qty_available(prod, warehouse) > 0:
                    return ("product", prod.id, None, node_index)
            except (TypeError, ValueError):
                pass
        global_coupon = ICP.get_param(GLOBAL_FALLBACK_COUPON_PARAM)
        if global_coupon:
            return ("coupon", False, global_coupon, node_index)
        raise SpinServiceError(
            "PRIZE_OUT_OF_STOCK",
            "Emergency fallback enabled but no global fallback configured",
        )

    def _check_top_prize_cooldown(self, user_id, warehouse_id, config):
        if not config.top_prize_cooldown_days or config.top_prize_cooldown_days <= 0:
            return
        Prize = self.env["lucky.wheel.prize"].sudo()
        from datetime import timedelta

        since = fields.Datetime.now() - timedelta(days=config.top_prize_cooldown_days)
        recent_top = Prize.search_count([
            ("user_id", "=", user_id),
            ("warehouse_id", "=", warehouse_id),
            ("is_top_prize", "=", True),
            ("state", "in", ("won", "pending", "redeemed")),
            ("won_at", ">=", since),
        ])
        if recent_top > 0:
            raise SpinServiceError(
                "TOP_PRIZE_COOLDOWN",
                "Top prize cooldown active",
            )

    def spin(self, user_id, warehouse_id, idempotency_key, request_id=None):
        """
        Execute spin. Returns dict with prize info and otp_required.

        :param user_id: res.users id
        :param warehouse_id: int
        :param idempotency_key: unique string (UUID recommended)
        :param request_id: optional
        :return: dict { prize_id, prize_type, product_id, coupon_payload, otp_required, otp }
        """
        self._check_kill_switch()
        if not idempotency_key or not str(idempotency_key).strip():
            raise SpinServiceError("VALIDATION_ERROR", "Idempotency-Key header is required")

        key = str(idempotency_key).strip()
        warehouse = self._resolve_warehouse(warehouse_id)
        config = self._get_config(warehouse)
        nodes = self._get_nodes(warehouse)

        Prize = self.env["lucky.wheel.prize"].sudo()
        Spend = self.env["lucky.wheel.spend"].sudo()

        # Idempotency: return existing prize if same key already used by this user+warehouse
        existing = Prize.search([
            ("idempotency_key", "=", key),
            ("user_id", "=", user_id),
            ("warehouse_id", "=", warehouse_id),
        ], limit=1)
        if existing:
            p = existing
            return {
                "prize_id": p.id,
                "prize_type": p.prize_type,
                "product_id": p.product_id.id if p.product_id else None,
                "product_name": p.product_id.name if p.product_id else None,
                "coupon_payload": p.coupon_payload,
                "otp_required": bool(p.otp_code_hash),
                "otp": None,
                "state": p.state,
                "expires_at": p.expires_at,
            }

        # Get or create spend
        spend = Spend.get_or_create(user_id, warehouse_id)
        threshold = config.threshold_amount or 200000
        credits = math.floor(spend.accumulated_paid_amount / threshold) - spend.spins_consumed

        if credits <= 0:
            raise SpinServiceError(
                "NO_SPIN_CREDITS",
                "Insufficient spin credits (need %s accumulated per spin)" % threshold,
            )

        # DB lock on spend
        self.env.cr.execute(
            "SELECT id FROM lucky_wheel_spend WHERE id = %s FOR UPDATE",
            (spend.id,),
        )
        self.env.cr.fetchall()

        # Recheck after lock
        spend._recompute_accumulated()
        spend.invalidate_recordset()
        credits = math.floor(spend.accumulated_paid_amount / threshold) - spend.spins_consumed
        if credits <= 0:
            raise SpinServiceError("NO_SPIN_CREDITS", "Insufficient spin credits")

        # Select node (weighted)
        node = self._select_node_weighted(nodes)
        # Resolve prize (handle OOS fallback)
        pt, product_id, coupon_payload, node_index = self._resolve_prize(node, config, warehouse, self.env.user)

        # Top prize cooldown (only if selected node is top prize)
        is_top = node.is_top_prize
        if is_top:
            self._check_top_prize_cooldown(user_id, warehouse_id, config)

        from datetime import timedelta

        expires_at = fields.Datetime.now() + timedelta(days=config.default_expire_days)

        # Create prize
        prize_vals = {
            "user_id": user_id,
            "warehouse_id": warehouse_id,
            "prize_type": pt,
            "product_id": product_id,
            "coupon_payload": coupon_payload,
            "state": "won",
            "idempotency_key": key,
            "node_index": node_index,
            "is_top_prize": is_top,
            "expires_at": expires_at,
        }
        prize = Prize.create(prize_vals)

        otp = None
        otp_required = pt in ("product", "coupon")
        if otp_required:
            otp = prize._generate_and_store_otp()

        spend.spins_consumed += 1

        return {
            "prize_id": prize.id,
            "prize_type": pt,
            "product_id": prize.product_id.id if prize.product_id else None,
            "product_name": prize.product_id.name if prize.product_id else None,
            "coupon_payload": prize.coupon_payload,
            "otp_required": otp_required,
            "otp": otp,
            "state": prize.state,
            "expires_at": prize.expires_at,
        }
