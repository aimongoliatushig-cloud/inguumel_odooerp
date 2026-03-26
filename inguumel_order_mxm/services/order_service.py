# -*- coding: utf-8 -*-
"""
Business logic for MXM order creation from cart.
Delivery info stored on sale.order; partner updated only when config enabled.
Order creation uses sudo() to bypass ir.sequence access restrictions for portal users.
"""
import logging
from odoo import models

_logger = logging.getLogger(__name__)


class OrderCreateError(Exception):
    """Raised when order creation fails. Carries API error code and message."""

    def __init__(self, code, message):
        self.code = code
        self.message = message
        super().__init__(message)


UPDATE_PARTNER_CONFIG = "mxm_order.update_partner_last_used"


class OrderService(models.AbstractModel):
    _name = "inguumel.order.service"
    _description = "MXM Order service (place order from cart)"

    def create_order_from_cart(
        self,
        partner_id,
        warehouse_id,
        phone_primary,
        phone_secondary,
        delivery_address,
        payment_method="cod",
        auto_confirm=True,
        request_id=None,
    ):
        """
        Create sale order from cart. Stores delivery info on order.
        Optionally updates partner when mxm_order.update_partner_last_used = "1".
        Clears cart lines after successful creation.

        Order creation uses sudo() to allow portal users to create orders
        (bypasses ir.sequence read restriction). Record rules are preserved
        by explicitly setting company_id and warehouse_id.

        :param partner_id: res.partner id (logged-in user's partner)
        :param warehouse_id: stock.warehouse id
        :param phone_primary: required
        :param phone_secondary: optional
        :param delivery_address: required
        :param payment_method: "cod" or "qpay_pending"
        :param auto_confirm: if True, confirm order; else leave draft
        :param request_id: optional request ID for tracing
        :return: sale.order record
        :raises OrderCreateError: on validation failure
        """
        env = self.env
        calling_uid = env.uid
        _logger.info(
            "create_order_from_cart: uid=%s partner_id=%s warehouse_id=%s request_id=%s",
            calling_uid, partner_id, warehouse_id, request_id,
        )

        Partner = env["res.partner"].sudo()
        Warehouse = env["stock.warehouse"].sudo()
        Cart = env["mxm.cart"].sudo()

        partner = Partner.browse(partner_id)
        if not partner.exists():
            raise OrderCreateError("ERROR", "Partner not found")

        warehouse = Warehouse.browse(warehouse_id)
        if not warehouse.exists():
            raise OrderCreateError("WAREHOUSE_REQUIRED", "Warehouse not found or invalid")

        # Get company from warehouse (for record rules)
        company_id = warehouse.company_id.id

        cart = Cart.get_or_create(partner_id, warehouse_id)
        if not cart.line_ids:
            raise OrderCreateError("CART_EMPTY", "Cart is empty")

        # Optionally update partner "last used" (config default "1" = enabled)
        update_partner = True
        try:
            ICP = env["ir.config_parameter"].sudo()
            val = ICP.get_param(UPDATE_PARTNER_CONFIG, "1")
            update_partner = val in ("1", "true", "True", "yes")
        except Exception:
            pass

        if update_partner:
            partner_vals = {
                "phone": (phone_primary or "").strip() or False,
                "street": (delivery_address or "").strip() or False,
            }
            if phone_secondary is not None and str(phone_secondary).strip():
                sec = str(phone_secondary).strip()
                if "x_phone_2" in Partner._fields:
                    partner_vals["x_phone_2"] = sec
                elif "mobile" in Partner._fields:
                    partner_vals["mobile"] = sec
            partner.write(partner_vals)

        # Build order lines from cart
        order_lines = []
        for line in cart.line_ids:
            if line.product_uom_qty <= 0:
                continue
            order_lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": line.product_id.id,
                        "product_uom_qty": line.product_uom_qty,
                        "product_uom_id": line.product_id.uom_id.id,
                        "price_unit": line.price_unit,
                    },
                )
            )

        if not order_lines:
            raise OrderCreateError("CART_EMPTY", "Cart has no valid lines")

        delivery_addr = (delivery_address or "").strip()
        order_vals = {
            "partner_id": partner_id,
            "company_id": company_id,
            "warehouse_id": warehouse_id,
            "order_line": order_lines,
            "note": delivery_addr or "",
            "origin": "MXM Mobile",
            "x_order_source": "mxm_cart",
            "x_delivery_address": delivery_addr,
            "x_phone_primary": (phone_primary or "").strip(),
            "x_phone_secondary": (phone_secondary or "").strip() if phone_secondary else "",
            "x_payment_method": payment_method or "cod",
        }

        # Use sudo() for create to bypass ir.sequence access restriction
        # Record rules preserved via explicit company_id/warehouse_id
        SaleOrder = env["sale.order"].sudo()
        order = SaleOrder.create(order_vals)

        # Defensive: ensure x_order_source set (order_vals already has mxm_cart)
        if not order.x_order_source and order.origin and "MXM" in (order.origin or ""):
            order.write({"x_order_source": "mxm_cart"})
            _logger.info("[MXM_ORDER] set x_order_source=mxm_cart for order %s", order.name)

        _logger.info(
            "create_order_from_cart: created order id=%s name=%s uid=%s request_id=%s",
            order.id, order.name, calling_uid, request_id,
        )

        # Confirm only when appropriate: COD can confirm immediately; QPay waits for callback
        should_confirm = False
        if payment_method == "qpay_pending":
            should_confirm = False
            _logger.info(
                "create_order_from_cart: qpay_pending order id=%s left draft, confirm after callback request_id=%s",
                order.id, request_id,
            )
        else:
            should_confirm = auto_confirm
        if should_confirm:
            order.action_confirm()
            _logger.info(
                "create_order_from_cart: confirmed order id=%s state=%s request_id=%s",
                order.id, order.state, request_id,
            )

        # Clear cart lines (already sudo)
        cart.line_ids.unlink()

        return order
