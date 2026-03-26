# -*- coding: utf-8 -*-
"""
MXM: entry log and transit/MTO blocking on product.product._get_rules_from_location path.
Used for debugging if stock.rule._get_rule ENTER never appears; and to block transit
when this path is used (e.g. orderpoint/reports) with mxm_block_transit.
"""
import logging

from odoo import _, models
from odoo.exceptions import UserError

from .stock_rule import _mxm_should_block_rule

_logger = logging.getLogger(__name__)


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _get_rules_from_location(self, location, route_ids=False, seen_rules=False):
        ctx_mxm = bool(self.env.context.get("mxm_block_transit"))
        _logger.info(
            "[MXM_RULE] ENTER _get_rules_from_location ctx_mxm=%s location=%s",
            ctx_mxm,
            location.id if location else None,
        )
        if not seen_rules:
            seen_rules = self.env["stock.rule"]
        warehouse = location.warehouse_id
        values = {"route_ids": route_ids, "warehouse_id": warehouse}
        rule = self.env["stock.rule"].with_context(active_test=True)._get_rule(
            self, location, values
        )
        if ctx_mxm and rule and _mxm_should_block_rule(rule):
            fallback = self.env["stock.rule"]._mxm_fallback_rule(values)
            if fallback:
                _logger.info(
                    "[MXM_RULE] REPLACE (product path) rule=%s -> fallback=%s",
                    rule.id,
                    fallback.id,
                )
                rule = fallback
        if rule in seen_rules:
            raise UserError(
                _(
                    "Invalid rule's configuration, the following rule causes an endless loop: %s",
                    rule.display_name,
                )
            )
        if not rule:
            return seen_rules
        if rule.procure_method == "make_to_stock" or rule.action not in (
            "pull_push",
            "pull",
        ):
            return seen_rules | rule
        return self._get_rules_from_location(
            rule.location_src_id, seen_rules=seen_rules | rule
        )
