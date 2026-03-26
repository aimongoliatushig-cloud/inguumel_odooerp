# -*- coding: utf-8 -*-
"""
MXM API orders: block route 1 (MTO) and Transit rules so procurement always uses
1-step delivery (WH/Stock -> Customers). Override _get_rule to replace
Transit/route-1 result with the warehouse outgoing rule when context mxm_block_transit.
"""
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Transit location id (Агуулах хоорондын хөдөлгөөн); fallback rule uses Customers instead.
MXM_TRANSIT_LOCATION_ID = 10
MXM_MTO_ROUTE_ID = 1


def _mxm_is_transit_location(loc):
    """Return True if location is Transit (usage or id=10)."""
    if not loc:
        return False
    return getattr(loc, "usage", None) == "transit" or (getattr(loc, "id", None) == 10)


def _mxm_should_block_rule(rule):
    """Return True if rule leads to Transit or is MTO (route_id=1)."""
    if not rule:
        return False
    if _mxm_is_transit_location(rule.location_dest_id):
        return True
    if rule.route_id and rule.route_id.id == MXM_MTO_ROUTE_ID:
        return True
    return False


class StockRule(models.Model):
    _inherit = "stock.rule"

    @api.model
    def _get_rule(self, *args, **kwargs):
        # Signature-safe for Odoo 19: accept any call style and parse robustly
        product_id = args[0] if len(args) > 0 else kwargs.get("product_id")
        location_id = args[1] if len(args) > 1 else kwargs.get("location_id")
        values = args[2] if len(args) > 2 else kwargs.get("values")
        if values is None:
            values = {}
        ctx_mxm = bool(self.env.context.get("mxm_block_transit"))
        _logger.info(
            "[MXM_RULE] ENTER _get_rule ctx_mxm=%s args=%s kwargs=%s",
            ctx_mxm,
            args,
            kwargs,
        )
        result = super()._get_rule(product_id, location_id, values)
        if not ctx_mxm:
            return result
        # When no rule found, try fallback to avoid "No rule has been found to replenish ... in Transit"
        if not result:
            fallback = self._mxm_fallback_rule(values)
            if fallback:
                _logger.info(
                    "[MXM_RULE] REPLACE empty rule -> fallback=%s (route=%s dest=%s)",
                    fallback.id,
                    fallback.route_id.id if fallback.route_id else None,
                    fallback.location_dest_id.id if fallback.location_dest_id else None,
                )
                return fallback
            return result
        if not _mxm_should_block_rule(result):
            return result
        fallback = self._mxm_fallback_rule(values)
        if fallback:
            _logger.info(
                "[MXM_RULE] REPLACE rule=%s route=%s dest=%s -> fallback=%s",
                result.id,
                result.route_id.id if result.route_id else None,
                result.location_dest_id.id if result.location_dest_id else None,
                fallback.id,
            )
            return fallback
        return result

    @api.model
    def _mxm_fallback_rule(self, values):
        """
        Find outgoing rule: warehouse from values/context, route from context
        mxm_force_route_id else warehouse.delivery_route_id else 3;
        action pull, picking_type code outgoing, location_dest usage customer.
        """
        env = self.env
        Warehouse = env["stock.warehouse"]
        wh = values.get("warehouse_id")
        if not wh:
            wid = env.context.get("force_warehouse_id") or env.context.get("warehouse_id")
            wh = Warehouse.browse(wid) if wid else Warehouse
        if isinstance(wh, int):
            wh = Warehouse.browse(wh)
        wh_id = wh.id if (hasattr(wh, "id") and wh) else (wh if isinstance(wh, int) else None)
        if not wh_id and hasattr(wh, "ids") and wh.ids:
            wh_id = wh.ids[0]
        if not wh_id:
            return self.env["stock.rule"]

        route_id = env.context.get("mxm_force_route_id")
        if not route_id and wh and hasattr(wh, "delivery_route_id") and wh.delivery_route_id:
            route_id = wh.delivery_route_id.id
        if not route_id:
            route_id = 3

        Route = env["stock.route"].sudo()
        route = Route.browse(route_id)
        if not route.exists() or not route.active:
            return self.env["stock.rule"]

        customer_loc = env["stock.location"].search(
            [("usage", "=", "customer")], limit=1
        )
        if not customer_loc:
            return self.env["stock.rule"]

        PickingType = env["stock.picking.type"].sudo()
        out_type = PickingType.search(
            [("warehouse_id", "=", wh_id), ("code", "=", "outgoing")],
            limit=1,
        )
        domain = [
            ("warehouse_id", "=", wh_id),
            ("route_id", "=", route_id),
            ("action", "in", ("pull", "pull_push")),
            ("location_dest_id", "=", customer_loc.id),
        ]
        if out_type:
            domain.append(("picking_type_id", "=", out_type.id))
        rule = self.sudo().search(domain, order="sequence, id", limit=1)
        return rule
