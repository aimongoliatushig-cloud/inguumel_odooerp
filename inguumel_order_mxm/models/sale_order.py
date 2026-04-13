# -*- coding: utf-8 -*-
"""Extend sale.order: delivery status (canonical), timeline logs, _mxm_set_status with transition validation.
When status transitions to 'delivered', outgoing pickings are validated so On Hand decreases (standard stock flow).

Product types and delivery (Odoo 14–19 sale_stock):
- product_id.type == 'product' (storable): delivery picking SHOULD be created; guard ensures we never confirm
  without an outgoing picking when routes and warehouse are valid.
- product_id.type == 'consu' (consumable): no stock move / no delivery picking.
- product_id.type == 'service': no picking.
"""
import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .mxm_order_status_log import MXM_DELIVERY_STATUS_CODES, STATUS_LABELS_MN

_logger = logging.getLogger(__name__)

# Race-condition guard: if last log has same status and is within this many seconds, skip creating duplicate log.
MXM_STATUS_DEDUP_SECONDS = 10

# Allowed transitions: no skipping, no invalid back. Key None = initial state.
MXM_ALLOWED_TRANSITIONS = {
    None: ["received"],
    "received": ["preparing", "cancelled"],
    "preparing": ["prepared", "cancelled"],
    "prepared": ["out_for_delivery", "cancelled"],
    "out_for_delivery": ["delivered", "cancelled"],
    "delivered": [],
    "cancelled": [],
}


class SaleOrder(models.Model):
    _inherit = "sale.order"

    x_delivery_address = fields.Text(string="Delivery Address")
    x_phone_primary = fields.Char(string="Primary Phone")
    x_phone_secondary = fields.Char(string="Secondary Phone")
    x_payment_method = fields.Selection(
        selection=[
            ("cod", "Cash on Delivery"),
            ("qpay_pending", "QPay (Pending)"),
            ("qpay_paid", "QPay (Paid)"),
            ("card_paid", "Card (Paid)"),
            ("wallet_paid", "Wallet (Paid)"),
        ],
        string="Payment Method",
        default="cod",
    )
    mxm_delivery_status = fields.Selection(
        selection=MXM_DELIVERY_STATUS_CODES,
        string="MXM Delivery Status",
        copy=False,
        index=True,
        readonly=True,
        help="Canonical delivery status (single source of truth). Updated only via Delivery Workbench or API.",
    )
    mxm_status_log_ids = fields.One2many(
        "mxm.order.status.log",
        "order_id",
        string="Status History",
        readonly=True,
    )
    mxm_last_status_code = fields.Char(
        string="Last MXM Status",
        compute="_compute_mxm_last_status_code",
        store=True,
        index=True,
        help="Last status from logs (for picking button visibility). Mirrors mxm_delivery_status.",
    )
    mxm_last_status_label_mn = fields.Char(
        string="Last MXM Status (MN)",
        compute="_compute_mxm_last_status_label_mn",
        store=True,
        index=True,
        help="Mongolian label for last status (ERP list/form).",
    )
    mxm_last_status_at = fields.Datetime(
        string="Last Status Change",
        compute="_compute_mxm_last_status_at",
        store=True,
        index=True,
        help="Datetime of last delivery status change (for Delivery list).",
    )
    mxm_timeline_html = fields.Html(
        string="Delivery Timeline",
        compute="_compute_mxm_timeline_html",
        sanitize=True,
        help="Read-only 5-step delivery timeline for Delivery Workbench.",
    )
    x_order_source = fields.Selection(
        selection=[
            ("mxm_mobile", "MXM Mobile"),
            ("mxm_cart", "MXM Cart"),
            ("pos", "POS"),
            ("backend", "Backend"),
        ],
        string="Order Source",
        index=True,
        copy=False,
        help="Source of the order. MXM orders get direct outgoing pickings without procurement.",
    )
    # COD auto-paid: operational flag for spend/eligibility (no accounting). Set by _check_auto_paid_cod.
    x_paid = fields.Boolean(string="Paid", default=False, copy=False)
    x_paid_at = fields.Datetime(string="Paid At", copy=False)
    x_cod_auto_paid = fields.Boolean(string="COD Auto-Paid", default=False, copy=False)
    x_cod_auto_paid_reason = fields.Char(string="COD Auto-Paid Reason", copy=False)
    # Cash Confirm (Cashier flow): set when cashier confirms COD received
    x_cash_confirmed_by = fields.Many2one(
        "res.users",
        string="Cash Confirmed By",
        copy=False,
        readonly=True,
        index=True,
        help="User (cashier/manager) who confirmed cash received for this COD order.",
    )
    x_cash_confirmed_at = fields.Datetime(
        string="Cash Confirmed At",
        copy=False,
        readonly=True,
        help="When cash was confirmed received (Cashier app / POS).",
    )
    x_cod_confirmed = fields.Boolean(string="COD Confirmed", default=False, copy=False, index=True)
    x_cod_confirmed_at = fields.Datetime(string="COD Confirmed At", copy=False, readonly=True, index=True)
    x_cod_confirmed_by = fields.Many2one("res.users", string="COD Confirmed By", copy=False, readonly=True, ondelete="set null", index=True)
    x_cod_amount = fields.Monetary(string="COD Amount", currency_field="company_currency_id", copy=False)
    company_currency_id = fields.Many2one("res.currency", related="company_id.currency_id", string="Company Currency", readonly=True)
    x_invoice_status_display = fields.Char(string="Invoice / Payment", compute="_compute_x_invoice_status_display")

    @api.depends("invoice_status", "x_payment_method", "x_cod_confirmed")
    def _compute_x_invoice_status_display(self):
        for order in self:
            if (getattr(order, "x_payment_method", None) or "") == "cod":
                order.x_invoice_status_display = "COD – Баталгаажсан" if getattr(order, "x_cod_confirmed", False) else "COD – Хүлээгдэж байна"
            else:
                inv_status = getattr(order, "invoice_status", None)
                order.x_invoice_status_display = {"no": "Nothing to Invoice", "to invoice": "To Invoice", "invoiced": "Fully Invoiced"}.get(inv_status, inv_status or "")

    @api.depends("mxm_status_log_ids", "mxm_status_log_ids.at")
    def _compute_mxm_last_status_at(self):
        for order in self:
            last = order.mxm_status_log_ids.sorted("at", reverse=True)[:1]
            order.mxm_last_status_at = last.at if last and last.at else None

    MXM_TIMELINE_CODES = ["received", "preparing", "prepared", "out_for_delivery", "delivered"]

    @api.depends("mxm_status_log_ids", "mxm_status_log_ids.code", "mxm_status_log_ids.at", "mxm_delivery_status")
    def _compute_mxm_timeline_html(self):
        for order in self:
            logs = order.mxm_status_log_ids.sorted("at") if order.mxm_status_log_ids else []
            last_code = order.mxm_delivery_status or order.mxm_last_status_code
            code_to_time = {log.code: (log.at.strftime("%H:%M") if log.at else "") for log in logs if log.code in self.MXM_TIMELINE_CODES}
            parts = []
            for code in self.MXM_TIMELINE_CODES:
                label = STATUS_LABELS_MN.get(code, code)
                time_str = code_to_time.get(code, "")
                if last_code == code:
                    icon, cls = "<span class=\"text-primary fw-bold\">●</span>", "text-primary fw-bold"
                elif code in code_to_time:
                    icon, cls = "<span class=\"text-success\">✓</span>", "text-success"
                else:
                    icon, cls = "<span class=\"text-muted\">○</span>", "text-muted"
                time_span = " <small class=\"text-muted\">{}</small>".format(time_str) if time_str else ""
                parts.append("<span class=\"mx-2 {}\">{} {}{}</span>".format(cls, icon, label, time_span))
            order.mxm_timeline_html = (
                "<div class=\"d-flex flex-wrap align-items-center justify-content-between border rounded p-2 mb-2\">"
                + " ".join(parts)
                + "</div>"
            ) if parts else False

    @api.depends("mxm_status_log_ids", "mxm_status_log_ids.code", "mxm_status_log_ids.at")
    def _compute_mxm_last_status_code(self):
        for order in self:
            last = order.mxm_status_log_ids.sorted("at", reverse=True)[:1]
            order.mxm_last_status_code = last.code if last else None

    @api.depends("mxm_last_status_code")
    def _compute_mxm_last_status_label_mn(self):
        for order in self:
            order.mxm_last_status_label_mn = (
                STATUS_LABELS_MN.get(order.mxm_last_status_code, order.mxm_last_status_code or "")
                if order.mxm_last_status_code
                else ""
            )

    def _mxm_ensure_initial_delivery_status(self):
        """
        Idempotent: ensure order has at least one delivery status log.
        If no logs exist, create a 'received' log (source=system) and set mxm_delivery_status.
        Used by GET /delivery and POST /delivery/status so old orders without status work.
        """
        self.ensure_one()
        Log = self.env["mxm.order.status.log"].sudo()
        last = Log.search(
            [("order_id", "=", self.id)],
            order="at desc, id desc",
            limit=1,
        )
        if last:
            return
        log_vals = {
            "order_id": self.id,
            "code": "received",
            "at": fields.Datetime.now(),
            "user_id": None,
            "note": None,
            "source": "system",
            "source_model": None,
            "source_id": 0,
        }
        Log.create(log_vals)
        self.sudo().write({"mxm_delivery_status": "received"})

    def _mxm_insufficient_stock_detail(self, picking):
        """Build detail string for insufficient-stock error: product names and required qty."""
        moves = picking.move_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
        )
        parts = [
            "%s (required %s)"
            % (m.product_id.display_name or m.product_id.name, m.product_uom_qty)
            for m in moves
        ]
        return "; ".join(parts) if parts else (picking.name or picking.id)

    def _mxm_validate_delivery_pickings(self):
        """
        Validate outgoing pickings for this order so stock is decreased (On Hand updated).
        Sets quantity_done on moves and calls button_validate. Idempotent: pickings already done are skipped.
        :return: (True, None) on success; (False, error_message) on failure (no picking, cannot reserve, etc.)
        """
        self.ensure_one()
        pickings = self.picking_ids.filtered(
            lambda p: p.picking_type_id and p.picking_type_id.code == "outgoing"
        )
        if not pickings:
            return False, "No delivery picking found. Confirm the order to create one."
        for picking in pickings:
            if picking.state == "done":
                continue
            if picking.state not in ("assigned", "confirmed", "waiting"):
                return False, "Delivery picking %s is in state %s; cannot validate." % (
                    picking.name or picking.id,
                    picking.state,
                )
            try:
                if picking.state in ("confirmed", "waiting"):
                    picking.action_assign()
                    picking.invalidate_recordset()
                    if picking.state not in ("assigned", "done"):
                        return False, (
                            "Insufficient stock: %s. Check On Hand in warehouse or adjust quantities."
                            % self._mxm_insufficient_stock_detail(picking)
                        )
                moves = picking.move_ids.filtered(
                    lambda m: m.state not in ("done", "cancel")
                )
                tracked = moves.filtered(
                    lambda m: (getattr(m.product_id, "tracking", None) or "none") != "none"
                )
                if tracked:
                    raise UserError(
                        _(
                            "One or more products require lot/serial. Please set lots in Inventory → Delivery and validate there."
                        )
                    )
                for move in moves:
                    move._set_quantity_done(move.product_uom_qty)
                result = picking.button_validate()
                if isinstance(result, dict) and result.get("res_model"):
                    wiz_model = result.get("res_model")
                    if wiz_model == "stock.immediate.transfer":
                        try:
                            wiz = (
                                self.env["stock.immediate.transfer"]
                                .sudo()
                                .with_context(
                                    active_model="stock.picking",
                                    active_ids=picking.ids,
                                    active_id=picking.id,
                                )
                                .create({})
                            )
                            if hasattr(wiz, "process"):
                                wiz.with_context(
                                    button_validate_picking_ids=picking.ids
                                ).process()
                        except Exception:
                            return False, "Validation requires user action. Complete delivery in Inventory."
                    elif wiz_model == "stock.backorder.confirmation":
                        try:
                            wiz = (
                                self.env["stock.backorder.confirmation"]
                                .sudo()
                                .with_context(
                                    active_model="stock.picking",
                                    active_ids=picking.ids,
                                    active_id=picking.id,
                                    button_validate_picking_ids=picking.ids,
                                )
                                .create(
                                    {
                                        "pick_ids": [(6, 0, picking.ids)],
                                    }
                                )
                            )
                            if hasattr(wiz, "process"):
                                wiz.process()
                            elif hasattr(wiz, "process_cancel_backorder"):
                                wiz.process_cancel_backorder()
                        except Exception:
                            return (
                                False,
                                "Validation requires user action (backorder or wizard). Complete delivery in Inventory.",
                            )
                    elif wiz_model == "confirm.stock.sms":
                        try:
                            wiz = (
                                self.env["confirm.stock.sms"]
                                .sudo()
                                .with_context(
                                    active_model="stock.picking",
                                    active_ids=picking.ids,
                                    active_id=picking.id,
                                    button_validate_picking_ids=picking.ids,
                                )
                                .create(
                                    {
                                        "pick_ids": [(6, 0, picking.ids)],
                                    }
                                )
                            )
                            if hasattr(wiz, "dont_send_sms"):
                                wiz.dont_send_sms()
                            elif hasattr(wiz, "send_sms"):
                                wiz.send_sms()
                        except Exception:
                            return (
                                False,
                                "Validation requires user action (SMS confirmation or wizard). Complete delivery in Inventory.",
                            )
                    else:
                        return False, "Validation requires user action (backorder or wizard). Complete delivery in Inventory."
                picking.invalidate_recordset()
            except UserError as e:
                return False, str(e)
            except Exception as e:
                return False, "Could not validate delivery: %s" % (str(e),)
        return True, None

    def _mxm_is_prepaid(self):
        """True if payment method is prepaid (stock decreases on confirm)."""
        return self.x_payment_method in ("qpay_paid", "card_paid", "wallet_paid")

    # COD auto-paid: driver app has no "cash received" button. Auto mark COD paid when delivered + delay.
    PAID_METHODS = ("qpay_paid", "card_paid", "wallet_paid")

    def _is_order_already_paid(self):
        """True if order is already considered paid (x_paid, payment_state, or prepaid method)."""
        if getattr(self, "x_paid", False):
            return True
        if hasattr(self, "payment_state") and getattr(self, "payment_state") == "paid":
            return True
        if getattr(self, "x_payment_method", None) in self.PAID_METHODS:
            return True
        return False

    def _get_delivered_at(self):
        """Return delivery completion time: last 'delivered' log at, or min picking.date_done of done outgoing."""
        order = self.sudo()
        Log = self.env["mxm.order.status.log"].sudo()
        last = Log.search(
            [("order_id", "=", order.id), ("code", "=", "delivered")],
            order="at desc",
            limit=1,
        )
        if last and last.at:
            return last.at
        outgoing = order._mxm_get_outgoing_pickings().filtered(lambda p: p.state == "done")
        if outgoing and any(p.date_done for p in outgoing):
            dates = [p.date_done for p in outgoing if p.date_done]
            return min(dates) if dates else None
        return None

    def _check_auto_paid_cod(self):
        """
        Auto mark COD orders as paid when delivered. Safeguards: kill switch, delay, only COD.
        Idempotent: skips if already paid. No invoices/accounting.
        IMPORTANT: When inguumel.cod_auto_paid_enabled is false, this method must NOT write x_paid
        (strict COD flow: only cashier Cash Confirm sets x_paid).
        """
        self.ensure_one()
        ICP = self.env["ir.config_parameter"].sudo()
        if ICP.get_param("inguumel.cod_auto_paid_enabled", "false").lower() not in ("1", "true", "yes"):
            return  # Do not set x_paid when disabled (strict cash-confirm flow)
        if getattr(self, "x_payment_method", None) != "cod":
            return
        if self.state not in ("sale", "done"):
            return
        if not self.amount_total or self.amount_total <= 0:
            return
        if self._is_order_already_paid():
            return
        outgoing = self._mxm_get_outgoing_pickings().filtered(lambda p: p.state == "done")
        if not outgoing:
            return
        delivered_at = self._get_delivered_at()
        if not delivered_at:
            return
        delay_minutes = int(ICP.get_param("inguumel.cod_auto_paid_delay_minutes", "10") or "10")
        now = fields.Datetime.now()
        threshold = now - timedelta(minutes=delay_minutes)
        if delivered_at > threshold:
            return
        self.sudo().write({
            "x_paid": True,
            "x_paid_at": now,
            "x_cod_auto_paid": True,
            "x_cod_auto_paid_reason": "delivered_done_outgoing",
        })
        msg = (
            "[AUTO_PAID_COD] order=%s partner=%s warehouse=%s total=%s reason=delivered_done_outgoing"
            % (self.name, self.partner_id.id, self.warehouse_id.id if self.warehouse_id else None, self.amount_total)
        )
        try:
            self.sudo().message_post(body=msg)
        except Exception:
            pass
        _logger.info(msg)

    def action_cash_confirm(self):
        """
        Cash Confirm: mark COD order as paid (cashier/manager only).
        Requires: COD, delivered, not yet paid.
        Sets x_paid, x_paid_at, x_cash_confirmed_by, x_cash_confirmed_at.
        Triggers Lucky Wheel accumulated recompute when module is present.
        """
        self.ensure_one()
        now = fields.Datetime.now()
        self.sudo().write({
            "x_paid": True,
            "x_paid_at": now,
            "x_cash_confirmed_by": self.env.user.id,
            "x_cash_confirmed_at": now,
            "x_cod_confirmed": True,
            "x_cod_confirmed_at": now,
            "x_cod_confirmed_by": self.env.user.id,
            "x_cod_amount": self.amount_total or 0,
        })
        self.env["mxm.order.status.log"].sudo().create({
            "order_id": self.id,
            "code": "cod_confirmed",
            "at": now,
            "user_id": self.env.user.id,
            "source": "staff",
            "note": "Cash confirmed by cashier",
        })
        msg = (
            "[CASH_CONFIRM] order=%s partner=%s warehouse=%s total=%s user=%s"
            % (
                self.name,
                self.partner_id.id,
                self.warehouse_id.id if self.warehouse_id else None,
                self.amount_total,
                self.env.user.id,
            )
        )
        try:
            self.sudo().message_post(body=msg)
        except Exception:
            pass
        _logger.info(msg)
        # Recompute Lucky Wheel accumulated for this partner+warehouse (if module installed)
        partner_id = self.partner_id.id if self.partner_id else None
        warehouse_id = self.warehouse_id.id if self.warehouse_id and self.warehouse_id.exists() else None
        if partner_id and warehouse_id:
            try:
                self.env["lucky.wheel.spend"].sudo()._recompute_for_partner_warehouse(
                    partner_id, warehouse_id
                )
            except KeyError:
                pass
        # COD cash-confirm is operational only: do NOT create/post invoices or register payments.
        # x_paid is the source of truth for COD; no dependency on account module.
        return True

    def _action_cod_confirm_driver(self, amount=None, note=None, user_id=None):
        """
        Driver COD confirm: set x_cod_confirmed, x_cod_confirmed_at, x_cod_confirmed_by, x_cod_amount;
        append timeline log code=cod_confirmed, source=driver. Idempotent if already confirmed.
        Does NOT create invoice or touch invoice_status.
        Returns (True, data_dict) or (False, error_message).
        """
        self.ensure_one()
        if getattr(self, "x_cod_confirmed", False):
            data = {
                "order_id": self.id,
                "x_cod_confirmed": True,
                "x_cod_confirmed_at": self.x_cod_confirmed_at.isoformat() if self.x_cod_confirmed_at else None,
                "x_cod_amount": float(self.x_cod_amount) if self.x_cod_amount else None,
            }
            return True, data
        cod_amount = amount if amount is not None and amount > 0 else (self.amount_total or 0)
        now = fields.Datetime.now()
        uid = user_id or self.env.user.id
        self.sudo().write({
            "x_cod_confirmed": True,
            "x_cod_confirmed_at": now,
            "x_cod_confirmed_by": uid,
            "x_cod_amount": cod_amount,
        })
        Log = self.env["mxm.order.status.log"].sudo()
        Log.create({
            "order_id": self.id,
            "code": "cod_confirmed",
            "at": now,
            "user_id": uid,
            "note": note,
            "source": "driver",
        })
        data = {
            "order_id": self.id,
            "x_cod_confirmed": True,
            "x_cod_confirmed_at": now.isoformat(),
            "x_cod_amount": float(cod_amount),
        }
        return True, data

    def _mxm_ensure_invoice_posted_and_paid_cod(self):
        """
        Ensure COD order has a posted customer invoice and it is paid (cash).
        Idempotent: no duplicate invoices/payments. Only runs when account module is present.
        Single source of truth: invoice payment_state=paid drives "Нэхэмжлэх ёстой" vs paid in UI.
        """
        self.ensure_one()
        if not hasattr(self, "invoice_ids") or not self.env.get("account.move"):
            return
        AccountMove = self.env["account.move"].sudo()
        invoices = (self.invoice_ids or self.env["account.move"]).filtered(
            lambda m: m.move_type == "out_invoice" and m.state != "cancel"
        )
        if not invoices and hasattr(self, "_create_invoices"):
            self._create_invoices()
            self.invalidate_recordset()
            invoices = (self.invoice_ids or self.env["account.move"]).filtered(
                lambda m: m.move_type == "out_invoice" and m.state != "cancel"
            )
        for inv in invoices:
            if inv.state == "draft":
                inv.action_post()
                inv.invalidate_recordset()
        cash_journal = self.env["account.journal"].sudo().search(
            [("type", "=", "cash")], limit=1
        )
        if not cash_journal:
            _logger.warning(
                "[CASH_CONFIRM] order=%s no cash journal found; invoice not paid via API",
                self.name,
            )
            return
        PaymentRegister = self.env.get("account.payment.register")
        if not PaymentRegister:
            return
        for inv in invoices:
            if inv.state != "posted":
                continue
            residual = getattr(inv, "amount_residual", None) or 0
            if residual <= 0:
                continue
            try:
                create_vals = {"journal_id": cash_journal.id}
                if hasattr(inv, "amount_residual"):
                    create_vals["amount"] = abs(inv.amount_residual)
                wiz = PaymentRegister.with_context(
                    active_model="account.move",
                    active_ids=inv.ids,
                ).create(create_vals)
                if hasattr(wiz, "action_create_payments"):
                    wiz.action_create_payments()
                elif hasattr(wiz, "create_payments"):
                    wiz.create_payments()
                else:
                    _logger.warning(
                        "[CASH_CONFIRM] order=%s invoice %s: no create_payments on wizard",
                        self.name,
                        inv.id,
                    )
            except Exception as e:
                _logger.warning(
                    "[CASH_CONFIRM] order=%s invoice %s register payment failed: %s",
                    self.name,
                    inv.id,
                    e,
                    exc_info=True,
                )

    def _mxm_get_outgoing_pickings(self):
        """Outgoing delivery pickings for this order, sorted by create_date."""
        pickings = self.picking_ids.filtered(
            lambda p: p.picking_type_id and p.picking_type_id.code == "outgoing"
        )
        return pickings.sorted("create_date")

    def _mxm_find_existing_return_picking(self):
        """Find an existing return picking for this order's outgoing deliveries (idempotency)."""
        outgoing = self._mxm_get_outgoing_pickings()
        if not outgoing:
            return self.env["stock.picking"]
        return self.env["stock.picking"].search(
            [("return_id", "in", outgoing.ids)], limit=1
        )

    def _mxm_validate_return_picking(self, return_picking):
        """Set qty_done and button_validate on a return picking. Returns (True, None) or (False, error_msg)."""
        self.ensure_one()
        if return_picking.state == "done":
            return True, None
        if return_picking.state not in ("assigned", "confirmed", "waiting"):
            return False, "Return picking %s is in state %s" % (
                return_picking.name or return_picking.id,
                return_picking.state,
            )
        try:
            if return_picking.state in ("confirmed", "waiting"):
                return_picking.action_assign()
                return_picking.invalidate_recordset()
                if return_picking.state not in ("assigned", "done"):
                    return False, "Insufficient stock to process return."
            moves = return_picking.move_ids.filtered(
                lambda m: m.state not in ("done", "cancel")
            )
            tracked = moves.filtered(
                lambda m: (getattr(m.product_id, "tracking", None) or "none") != "none"
            )
            if tracked:
                return False, _(
                    "One or more products require lot/serial. Set lots in Inventory and validate there."
                )
            for move in moves:
                move._set_quantity_done(move.product_uom_qty)
            result = return_picking.button_validate()
            if isinstance(result, dict) and result.get("res_model") == "stock.immediate.transfer":
                wiz = (
                    self.env["stock.immediate.transfer"]
                    .sudo()
                    .with_context(
                        active_model="stock.picking",
                        active_ids=return_picking.ids,
                        active_id=return_picking.id,
                    )
                    .create({})
                )
                if hasattr(wiz, "process"):
                    wiz.with_context(button_validate_picking_ids=return_picking.ids).process()
            return_picking.invalidate_recordset()
            return True, None
        except UserError as e:
            return False, str(e)
        except Exception as e:
            return False, "Could not validate return: %s" % (str(e),)

    def _mxm_create_and_validate_return(self):
        """
        Create return pickings for done outgoing deliveries, or use existing (idempotency).
        Validate each return so stock comes back. Returns (True, None) or (False, error_msg).
        """
        self.ensure_one()
        outgoing = self._mxm_get_outgoing_pickings().filtered(lambda p: p.state == "done")
        if not outgoing:
            return False, "No done delivery picking to return."
        for picking in outgoing:
            # Idempotency: reuse existing return for this picking if any
            existing_return = self.env["stock.picking"].search(
                [("return_id", "=", picking.id)], limit=1
            )
            if existing_return:
                ok, err = self._mxm_validate_return_picking(existing_return)
                if not ok:
                    return False, err or "Return could not be validated."
                continue
            try:
                ReturnWizard = self.env["stock.return.picking"].sudo().with_context(
                    active_id=picking.id,
                    active_ids=[picking.id],
                    active_model="stock.picking",
                )
                wizard = ReturnWizard.create({"picking_id": picking.id})
                action = wizard.action_create_returns_all()
                return_picking = self.env["stock.picking"].browse(action.get("res_id"))
            except UserError as e:
                return False, str(e)
            except Exception as e:
                return False, "Return could not be created: %s" % (str(e),)
            if not return_picking.exists():
                return False, "Return picking could not be created."
            ok, err = self._mxm_validate_return_picking(return_picking)
            if not ok:
                return False, err
        return True, None

    def _mxm_cancel_order(self):
        """
        Cancel order: unreserve if picking not done; create/validate return if done (prepaid).
        Returns (True, None) or (False, error_message).
        """
        self.ensure_one()
        if self.state == "cancel":
            return True, None
        if self.mxm_delivery_status == "cancelled":
            return True, None
        pickings = self._mxm_get_outgoing_pickings()
        if not pickings:
            self.sudo().action_cancel()
            return True, None
        done_pickings = pickings.filtered(lambda p: p.state == "done")
        if done_pickings:
            ok, err = self.sudo()._mxm_create_and_validate_return()
            if not ok:
                return False, err or "Return could not be created or validated."
        else:
            for picking in pickings:
                moves = picking.move_ids.filtered(
                    lambda m: m.state not in ("done", "cancel")
                )
                if moves:
                    moves._do_unreserve()
        self.sudo().action_cancel()
        return True, None

    def _mxm_ensure_reservation(self):
        """
        Ensure outgoing pickings are assigned (reserved).
        :return: (True, None) on success; (False, err_msg, "OUT_OF_STOCK") on failure
        """
        self.ensure_one()
        pickings = self._mxm_get_outgoing_pickings().filtered(
            lambda p: p.state not in ("done", "cancel")
        )
        if not pickings:
            return True, None, None
        for picking in pickings:
            if picking.state in ("confirmed", "waiting"):
                picking.action_assign()
                picking.invalidate_recordset()
            if picking.state not in ("assigned", "done"):
                detail = self._mxm_insufficient_stock_detail(picking)
                return (
                    False,
                    "Insufficient stock: %s. Check On Hand in warehouse or adjust quantities." % detail,
                    "OUT_OF_STOCK",
                )
        return True, None, None

    def _mxm_set_status(
        self,
        status,
        note=None,
        source="system",
        source_model=None,
        source_id=None,
        user_id=None,
    ):
        """
        Validate transition, perform picking actions, write log, update mxm_delivery_status.
        Transaction-like: picking actions FIRST, timeline write ONLY after success.
        Blocks fake timeline: requires outgoing picking for statuses that imply stock movement.
        :return: (ok, err_msg, error_code, stock_effect)
        """
        self.ensure_one()
        current = self.mxm_delivery_status
        stock_effect = "none"

        if not status or status not in dict(MXM_DELIVERY_STATUS_CODES):
            return False, "Invalid status code", "VALIDATION_ERROR", None
        self._mxm_ensure_initial_delivery_status()
        current = self.mxm_delivery_status
        allowed = MXM_ALLOWED_TRANSITIONS.get(current, [])
        if status not in allowed:
            return False, "Transition from %s to %s not allowed" % (current or "None", status), "VALIDATION_ERROR", None
        if current == status:
            return True, None, None, "none"

        pickings = self._mxm_get_outgoing_pickings().filtered(lambda p: p.state != "cancel")
        picking_info = [(p.id, p.name or "", p.state) for p in pickings]

        _logger.info(
            "[DELIVERY_STATUS_REQ] order_id=%s order_name=%s from=%s to=%s pickings=%s",
            self.id,
            self.name or "(no name)",
            current or "None",
            status,
            picking_info,
        )

        if not pickings and not (current is None and status == "received"):
            if self.state == "sale":
                try:
                    self.sudo()._mxm_repair_missing_outgoing_picking()
                    self.invalidate_recordset()
                    pickings = self._mxm_get_outgoing_pickings().filtered(lambda p: p.state != "cancel")
                    if pickings:
                        _logger.info(
                            "[PICKING_REPAIR] order_id=%s repair created pickings=%s",
                            self.id,
                            pickings.ids,
                        )
                except Exception as e:
                    _logger.warning(
                        "[PICKING_REPAIR] order_id=%s repair failed: %s",
                        self.id,
                        e,
                    )
            if not pickings:
                _logger.warning(
                    "[PICKING_FOUND] order_id=%s NO outgoing pickings; blocking status=%s",
                    self.id,
                    status,
                )
                return (
                    False,
                    "No delivery picking found. Confirm the order to create one.",
                    "NO_DELIVERY_PICKING",
                    None,
                )

        _logger.info(
            "[PICKING_FOUND] order_id=%s pickings=%s",
            self.id,
            picking_info,
        )

        if status == "prepared":
            ok_res, err_res, err_code = self.sudo()._mxm_ensure_reservation()
            if not ok_res:
                _logger.warning(
                    "[PICKING_ASSIGN] order_id=%s failed: %s",
                    self.id,
                    err_res or "",
                )
                return False, err_res or "Could not reserve stock.", err_code or "OUT_OF_STOCK", None
            for p in pickings:
                if p.state not in ("done", "cancel"):
                    _logger.info(
                        "[PICKING_ASSIGN] picking_id=%s picking_name=%s result_state=%s",
                        p.id,
                        p.name or "",
                        p.state,
                    )
            stock_effect = "reserved"

        elif status == "out_for_delivery":
            ok_res, err_res, err_code = self.sudo()._mxm_ensure_reservation()
            if not ok_res:
                return False, err_res or "Could not reserve stock.", err_code or "OUT_OF_STOCK", None
            stock_effect = "reserved"

        elif status == "delivered":
            ok_val, err_val = self.sudo()._mxm_validate_delivery_pickings()
            if not ok_val:
                _logger.warning(
                    "[PICKING_VALIDATE] order_id=%s failed: %s",
                    self.id,
                    err_val or "",
                )
                return (
                    False,
                    err_val or "Delivery picking could not be validated.",
                    "VALIDATION_ERROR",
                    None,
                )
            for p in pickings:
                _logger.info(
                    "[PICKING_VALIDATE] picking_id=%s picking_name=%s result_state=%s validated=True",
                    p.id,
                    p.name or "",
                    p.state,
                )
            stock_effect = "validated"

        elif status == "cancelled":
            ok_cancel, err_cancel = self.sudo()._mxm_cancel_order()
            if not ok_cancel:
                return False, err_cancel or "Could not cancel order.", "VALIDATION_ERROR", None

        Log = self.env["mxm.order.status.log"].sudo()
        last = Log.search(
            [("order_id", "=", self.id)],
            order="at desc, id desc",
            limit=1,
        )
        if last and last.code == status:
            now = fields.Datetime.now()
            if last.at and (now - last.at).total_seconds() < MXM_STATUS_DEDUP_SECONDS:
                _logger.info(
                    "[DELIVERY_STATUS_COMMIT] order_id=%s status=%s stock_effect=%s (dedup skip)",
                    self.id,
                    status,
                    stock_effect,
                )
                return True, None, None, stock_effect

        log_vals = {
            "order_id": self.id,
            "code": status,
            "at": fields.Datetime.now(),
            "user_id": user_id or (self.env.user.id if self.env.user and not self.env.user._is_public() else None),
            "note": note,
            "source": source,
            "source_model": source_model,
            "source_id": source_id or 0,
        }
        Log.create(log_vals)
        self.sudo().write({"mxm_delivery_status": status})

        if status == "delivered":
            try:
                self._check_auto_paid_cod()
            except Exception as e:
                _logger.warning("[AUTO_PAID_COD] hook failed order=%s: %s", self.id, e)

        _logger.info(
            "[DELIVERY_STATUS_COMMIT] order_id=%s order_name=%s status=%s stock_effect=%s",
            self.id,
            self.name or "(no name)",
            status,
            stock_effect,
        )
        return True, None, None, stock_effect

    @api.model
    def _cron_cod_auto_paid(self):
        """
        Cron: find delivered COD orders not paid, apply auto-paid if delay satisfied.
        Batch limit 200, ordered by earliest picking.date_done.
        """
        ICP = self.env["ir.config_parameter"].sudo()
        if ICP.get_param("inguumel.cod_auto_paid_enabled", "false").lower() not in ("1", "true", "yes"):
            return
        orders = self.search([
            ("x_payment_method", "=", "cod"),
            ("state", "in", ("sale", "done")),
            ("amount_total", ">", 0),
            ("x_paid", "=", False),
            ("mxm_delivery_status", "=", "delivered"),
        ], order="id asc", limit=200)
        for order in orders:
            try:
                order._check_auto_paid_cod()
            except Exception as e:
                _logger.warning("[AUTO_PAID_COD] cron order=%s: %s", order.id, e)

    def action_mxm_preparing(self):
        """Delivery Workbench: set status preparing (only when transition allowed)."""
        self.ensure_one()
        ok, err_msg, error_code, stock_effect = self._mxm_set_status("preparing", source="staff", note="From Delivery Workbench")
        if not ok:
            raise UserError(err_msg or "Transition not allowed")
        return True

    def action_mxm_prepared(self):
        """Delivery Workbench: set status prepared."""
        self.ensure_one()
        ok, err_msg, error_code, stock_effect = self._mxm_set_status("prepared", source="staff", note="From Delivery Workbench")
        if not ok:
            raise UserError(err_msg or "Transition not allowed")
        return True

    def action_mxm_out_for_delivery(self):
        """Delivery Workbench: set status out_for_delivery."""
        self.ensure_one()
        ok, err_msg, error_code, stock_effect = self._mxm_set_status("out_for_delivery", source="staff", note="From Delivery Workbench")
        if not ok:
            raise UserError(err_msg or "Transition not allowed")
        return True

    def action_mxm_delivered(self):
        """Delivery Workbench: set status delivered."""
        self.ensure_one()
        ok, err_msg, error_code, stock_effect = self._mxm_set_status("delivered", source="staff", note="From Delivery Workbench")
        if not ok:
            raise UserError(err_msg or "Transition not allowed")
        return True

    def _mxm_log_confirm_diagnostics(self, stage="before"):
        """Log diagnostics to expose common root causes when no delivery picking is created.
        Logs: order_id, state, company_id, warehouse_id, warehouse_outgoing_ok,
        per-line product_id, product_id.type, route_ids, pickings_count, outgoing_count.
        Root causes exposed: missing/wrong product or category route; warehouse has no
        outgoing picking type; warehouse/company mismatch; order created with wrong company_id.
        """
        self.ensure_one()
        order = self
        try:
            company_id = order.company_id.id if order.company_id else None
            warehouse_id = order.warehouse_id.id if order.warehouse_id else None
            warehouse_delivery_ok = False
            if order.warehouse_id and order.warehouse_id.exists():
                out_type = (
                    self.env["stock.picking.type"]
                    .sudo()
                    .search(
                        [
                            ("warehouse_id", "=", order.warehouse_id.id),
                            ("code", "=", "outgoing"),
                        ],
                        limit=1,
                    )
                )
                warehouse_delivery_ok = bool(out_type)
            line_info = []
            for line in (order.order_line or []):
                if not line.product_id:
                    continue
                ptype = getattr(line.product_id, "type", None)
                is_storable = getattr(line.product_id, "is_storable", None)
                route_ids = []
                if hasattr(line, "route_ids") and line.route_ids:
                    route_ids = line.route_ids.ids
                line_info.append(
                    {
                        "product_id": line.product_id.id,
                        "product_type": ptype,
                        "is_storable": is_storable,
                        "route_ids": route_ids,
                    }
                )
            pickings_count = len(order.picking_ids) if order.picking_ids else 0
            outgoing_count = len(order._mxm_get_outgoing_pickings())
            _logger.info(
                "[CONFIRM_%s] order_id=%s order_name=%s state=%s company_id=%s warehouse_id=%s "
                "warehouse_outgoing_ok=%s lines=%s pickings_count=%s outgoing_count=%s",
                stage.upper(),
                order.id,
                order.name or "(no name)",
                order.state,
                company_id,
                warehouse_id,
                warehouse_delivery_ok,
                line_info,
                pickings_count,
                outgoing_count,
            )
        except Exception as e:
            _logger.warning("[CONFIRM_%s] diagnostic log failed order_id=%s: %s", stage.upper(), order.id, e)

    def _mxm_is_mxm_order(self):
        """True if this order is from MXM (mobile/cart); use x_order_source, not origin text."""
        return self.x_order_source in ("mxm_mobile", "mxm_cart")

    def _mxm_get_customer_location(self, warehouse):
        """Resolve Customers location (usage=customer) for outgoing moves. Prefer ref, else search by usage."""
        self.ensure_one()
        customer_loc = self.env.ref("stock.stock_location_customers", raise_if_not_found=False)
        if customer_loc and customer_loc.exists():
            return customer_loc
        Location = self.env["stock.location"].sudo()
        domain = [("usage", "=", "customer")]
        if warehouse and warehouse.company_id:
            domain.append(("company_id", "in", (False, warehouse.company_id.id)))
        customer_loc = Location.search(domain, limit=1)
        if not customer_loc:
            raise UserError(_("Customer stock location not found. Create a location with usage=Customer."))
        return customer_loc

    def _mxm_create_outgoing_picking_impl(self, warehouse, partner):
        """Create one outgoing stock.picking (WH/Stock -> Customers) for this order. No procurement."""
        self.ensure_one()
        picking_type = warehouse.out_type_id
        if not picking_type:
            raise UserError(_("Warehouse OUT picking type (out_type_id) not found."))
        src_loc = warehouse.lot_stock_id
        if not src_loc:
            raise UserError(_("Warehouse stock location (lot_stock_id) not found."))
        dest_loc = self._mxm_get_customer_location(warehouse)
        Picking = self.env["stock.picking"].sudo()
        Move = self.env["stock.move"].sudo()
        picking = Picking.create({
            "picking_type_id": picking_type.id,
            "location_id": src_loc.id,
            "location_dest_id": dest_loc.id,
            "origin": self.name,
            "partner_id": partner.id,
            "company_id": self.company_id.id,
        })
        for line in self.order_line:
            qty = getattr(line, "product_uom_qty", 0) or 0
            if not line.product_id or qty <= 0:
                continue
            uom = getattr(line, "product_uom_id", None) or line.product_id.uom_id
            Move.create({
                "description_picking": (line.name or line.product_id.display_name or ""),
                "product_id": line.product_id.id,
                "product_uom": uom.id,
                "product_uom_qty": qty,
                "picking_id": picking.id,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
                "company_id": self.company_id.id,
                "sale_line_id": line.id,
            })
        picking.action_confirm()
        picking.action_assign()
        _logger.info(
            "[MXM_PICKING] created outgoing picking picking_id=%s order=%s src=%s dst=%s",
            picking.id,
            self.name,
            getattr(src_loc, "complete_name", src_loc.name),
            getattr(dest_loc, "complete_name", dest_loc.name),
        )
        return picking

    def _mxm_ensure_outgoing_picking(self, warehouse=None, partner=None):
        """Idempotent: return existing OUTGOING picking (origin, type=outgoing, same warehouse) or create one.
        Does NOT skip when only incoming/internal pickings exist.
        """
        self.ensure_one()
        wh = warehouse or self.warehouse_id
        if not wh or not wh.exists():
            raise UserError(_("No warehouse on order %s.") % (self.name or self.id))

        # Defensive: set x_order_source from origin when missing for MXM
        if self.x_order_source not in ("mxm_mobile", "mxm_cart") and self.origin and "MXM" in (self.origin or ""):
            src = "mxm_cart" if "MXM Cart" in (self.origin or "") else "mxm_mobile"
            self.sudo().write({"x_order_source": src})
            _logger.info("[MXM_ORDER] set x_order_source=%s for order %s", src, self.name)

        if self.x_order_source not in ("mxm_mobile", "mxm_cart"):
            return self.env["stock.picking"]

        # Only OUTGOING pickings for this order + warehouse (ignore incoming/internal)
        existing_out = self.env["stock.picking"].sudo().search([
            ("origin", "=", self.name),
            ("picking_type_id.code", "=", "outgoing"),
            ("picking_type_id.warehouse_id", "=", wh.id),
        ], limit=1)
        if existing_out:
            _logger.info(
                "[MXM_PICKING] skip create (outgoing exists) order=%s picking_id=%s wh=%s",
                self.name,
                existing_out.id,
                wh.id,
            )
            return existing_out

        part = partner or self.partner_shipping_id or self.partner_id
        if not part:
            raise UserError(_("No partner on order %s.") % (self.name or self.id))
        picking = self._mxm_create_outgoing_picking_impl(wh, part)
        return picking

    @api.model
    def _mxm_recover_missing_pickings(self, dry_run=True, order_ids=None):
        """Find confirmed MXM orders with no outgoing picking and create pickings. Supports dry_run.
        Includes orders with x_order_source in (mxm_mobile, mxm_cart) OR origin containing 'MXM'
        (for legacy S00014+ without x_order_source). Sets x_order_source from origin when missing.
        Returns dict with dry_run, order_count/order_names (if dry_run) or created list (order_name, picking_id).
        """
        if order_ids is None:
            orders = self.search([
                ("state", "=", "sale"),
                "|",
                ("x_order_source", "in", ["mxm_mobile", "mxm_cart"]),
                "&",
                ("origin", "ilike", "MXM"),
                ("x_order_source", "=", False),
            ])
        else:
            orders = self.browse(order_ids).exists().filtered(
                lambda o: o.state == "sale"
                and (o.x_order_source in ("mxm_mobile", "mxm_cart") or (o.origin and "MXM" in (o.origin or "")))
            )
        need = orders.filtered(lambda o: not o._mxm_get_outgoing_pickings())
        if dry_run:
            return {
                "dry_run": True,
                "order_count": len(need),
                "order_names": need.mapped("name"),
                "order_ids": need.ids,
            }
        created = []
        for order in need:
            try:
                if not order.x_order_source and order.origin and "MXM" in (order.origin or ""):
                    src = "mxm_cart" if "MXM Cart" in (order.origin or "") else "mxm_mobile"
                    order.sudo().write({"x_order_source": src})
                    _logger.info("[MXM_ORDER] set x_order_source=%s for order %s", src, order.name)
                pick = order._mxm_ensure_outgoing_picking()
                if pick:
                    created.append((order.name, pick.id))
            except Exception as e:
                _logger.exception(
                    "_mxm_recover_missing_pickings order=%s: %s",
                    order.name,
                    e,
                )
        return {"dry_run": False, "created": created}

    def _mxm_repair_missing_outgoing_picking(self):
        """One-time repair: create missing outgoing picking for orders already in state='sale'.
        Uses sale_stock procurement (_action_launch_stock_rule), NOT action_confirm().
        Idempotent: if outgoing picking already exists, no-op and return existing.
        :return: list of created (or existing) outgoing picking ids for self.
        """
        self.ensure_one()
        if self.state != "sale":
            _logger.warning(
                "_mxm_repair_missing_outgoing_picking order=%s state=%s (expected sale), skip",
                self.name,
                self.state,
            )
            return []
        existing = self._mxm_get_outgoing_pickings()
        if existing:
            _logger.info(
                "_mxm_repair_missing_outgoing_picking order=%s already has outgoing picking_ids=%s",
                self.name,
                existing.ids,
            )
            return existing.ids
        self._mxm_ensure_delivery_routes_for_mobile()
        self.order_line.sudo()._action_launch_stock_rule(previous_product_uom_qty=False)
        self.invalidate_recordset()
        created = self._mxm_get_outgoing_pickings()
        if created:
            _logger.info(
                "_mxm_repair_missing_outgoing_picking order=%s created picking_ids=%s",
                self.name,
                created.ids,
            )
        return created.ids

    @api.model
    def _mxm_repair_missing_pickings_batch(self, order_ids=None):
        """Server-side repair for orders in state='sale' with no outgoing picking.
        Uses _action_launch_stock_rule (sale_stock). Call from shell or script.
        :param order_ids: optional list of sale.order ids (e.g. [51, 52])
        :return: dict with order_ids_processed, created {order_id: [picking_id, ...]}, errors {order_id: str}
        """
        if order_ids is not None:
            orders = self.browse(order_ids).exists().filtered(lambda o: o.state == "sale")
        else:
            orders = self.search([("state", "=", "sale")])
        need = orders.filtered(lambda o: not o._mxm_get_outgoing_pickings())
        created = {}
        errors = {}
        for order in need:
            try:
                picking_ids = order.sudo()._mxm_repair_missing_outgoing_picking()
                if picking_ids:
                    created[order.id] = picking_ids
            except Exception as e:
                errors[order.id] = str(e)
                _logger.exception(
                    "_mxm_repair_missing_pickings_batch order_id=%s: %s",
                    order.id,
                    e,
                )
        return {
            "order_ids_processed": need.ids,
            "created": created,
            "errors": errors,
        }

    @api.model
    def _mxm_fix_outgoing_picking_destinations(self, dry_run=True):
        """Fix outgoing pickings (origin like S%) whose location_dest_id is not Customers.
        Updates picking and its moves to use Customers location. Safe dry_run option.
        Returns dict with dry_run, updated_count, updated [(picking_id, picking_name, old_dest, new_dest)].
        """
        Picking = self.env["stock.picking"].sudo()
        customer_loc = self.env.ref("stock.stock_location_customers", raise_if_not_found=False)
        if not customer_loc or not customer_loc.exists():
            customer_loc = self.env["stock.location"].sudo().search(
                [("usage", "=", "customer")], limit=1
            )
        if not customer_loc:
            return {"dry_run": dry_run, "error": "Customer location not found", "updated": []}
        wrong = Picking.search([
            ("origin", "ilike", "S%"),
            ("picking_type_id.code", "=", "outgoing"),
            ("location_dest_id.usage", "!=", "customer"),
        ])
        if dry_run:
            return {
                "dry_run": True,
                "updated_count": len(wrong),
                "updated": [
                    (p.id, p.name, getattr(p.location_dest_id, "complete_name", p.location_dest_id.name), customer_loc.complete_name)
                    for p in wrong
                ],
            }
        updated = []
        for picking in wrong:
            try:
                old_dest = getattr(picking.location_dest_id, "complete_name", picking.location_dest_id.name)
                picking.write({"location_dest_id": customer_loc.id})
                picking.move_ids.write({"location_dest_id": customer_loc.id})
                if picking.move_line_ids:
                    picking.move_line_ids.write({"location_dest_id": customer_loc.id})
                updated.append((picking.id, picking.name, old_dest, customer_loc.complete_name))
                _logger.info(
                    "[MXM_PICKING] fixed destination picking_id=%s order=%s old_dest=%s new_dest=%s",
                    picking.id,
                    picking.origin,
                    old_dest,
                    customer_loc.complete_name,
                )
            except Exception as e:
                _logger.exception(
                    "_mxm_fix_outgoing_picking_destinations picking_id=%s: %s",
                    picking.id,
                    e,
                )
        return {"dry_run": False, "updated_count": len(updated), "updated": updated}

    def action_confirm(self):
        """Ensure mobile orders have delivery routes before confirm; then super().action_confirm();
        then guard: if order has storable products and no outgoing picking, log diagnostics and raise UserError.
        After confirm, reserve stock on outgoing pickings (action_assign) so free_qty decreases.
        For MXM orders (x_order_source in mxm_mobile/mxm_cart): force route on lines and context.
        """
        for order in self:
            order._mxm_log_confirm_diagnostics(stage="before")
        # Step 2: ensure delivery routes for mobile orders BEFORE procurement runs.
        self._mxm_ensure_delivery_routes_for_mobile()

        # B2: MXM orders (by x_order_source) confirm with context so procurement uses only warehouse ship rule.
        mxm = self.filtered(lambda o: o.x_order_source in ("mxm_mobile", "mxm_cart"))
        other = self - mxm
        result = True
        if mxm:
            for order in mxm:
                wh = order.warehouse_id
                route = wh.delivery_route_id if wh and wh.delivery_route_id and wh.delivery_route_id.exists() else self.env["stock.route"].sudo().browse(3)
                if route and route.exists():
                    order.order_line.sudo().write({"route_ids": [(6, 0, [route.id])]})
            result = super(SaleOrder, mxm.with_context(
                disable_mto=True,
                force_warehouse_id=mxm[:1].warehouse_id.id,
                warehouse_id=mxm[:1].warehouse_id.id,
            )).action_confirm()
        if other:
            result2 = super(SaleOrder, other).action_confirm()
            result = result2 if result is True else result

        for order in self:
            order._mxm_log_confirm_diagnostics(stage="after")
            if order.state != "sale":
                continue
            # Odoo 19: is_storable=True for storable; older Odoo: type=='product'
            has_storable = any(
                line.product_id
                and (
                    getattr(line.product_id, "is_storable", False)
                    or getattr(line.product_id, "type", None) == "product"
                )
                for line in (order.order_line or [])
            )
            if not has_storable:
                continue
            pickings = order._mxm_get_outgoing_pickings()
            if not pickings:
                order._mxm_log_confirm_diagnostics(stage="guard_fail")
                raise UserError(
                    _("Delivery picking was not created. Check product routes and warehouse configuration.")
                )
            # Reserve stock on outgoing pickings (reduces free_qty, prevents overselling)
            for picking in pickings:
                try:
                    if picking.state in ("confirmed", "waiting"):
                        picking.action_assign()
                        picking.invalidate_recordset()
                    assigned = picking.state == "assigned"
                    _logger.info(
                        "[RESERVE] order_id=%s order_name=%s picking_id=%s picking_name=%s "
                        "assigned=%s state=%s",
                        order.id,
                        order.name or "(no name)",
                        picking.id,
                        picking.name or "",
                        assigned,
                        picking.state,
                    )
                except Exception as e:
                    _logger.warning(
                        "[RESERVE] order_id=%s picking_id=%s action_assign failed: %s",
                        order.id,
                        picking.id,
                        e,
                    )
        return result

    def _mxm_ensure_delivery_routes_for_mobile(self):
        """For mobile-created orders: force warehouse delivery route (1-step ship) on lines with
        storable or consumable products. Ensures native procurement uses WH/Stock -> Customers
        and does NOT use MTO/transit rules that would require replenishment in Transit location.

        Odoo may set line.route_ids from product.route_ids or product.categ_id; if those
        include MTO or a route with a rule to Transit, confirmation fails with "No rule has been
        found to replenish ... in 'Transit'". We overwrite with warehouse.delivery_route_id so
        only the 1-step delivery rule (src=Stock, dest=Customers) is used.
        Applies only when order.x_order_source is mxm_mobile/mxm_cart; POS and backend are unchanged.
        """
        for order in self:
            if order.x_order_source not in ("mxm_mobile", "mxm_cart"):
                continue
            wh = order.warehouse_id
            if not wh or not wh.exists() or not wh.delivery_route_id:
                continue
            if wh.company_id.id != order.company_id.id:
                continue
            route = wh.delivery_route_id
            if not route.exists() or not route.sale_selectable:
                continue
            for line in order.order_line or []:
                if not line.product_id:
                    continue
                if getattr(line, "display_type", None) or getattr(line, "is_downpayment", False):
                    continue
                ptype = getattr(line.product_id, "type", None)
                is_storable = getattr(line.product_id, "is_storable", False) or ptype == "product"
                is_consu = ptype == "consu"
                if not (is_storable or is_consu):
                    continue
                # Force warehouse delivery route (overwrite product/category routes that may
                # point to MTO or Transit and cause "replenish in Transit" errors).
                try:
                    line.sudo().write({"route_ids": [(6, 0, [route.id])]})
                    _logger.info(
                        "[MXM_ROUTE_FALLBACK] order_id=%s order_name=%s line_id=%s product_id=%s set route_ids=[%s]",
                        order.id,
                        order.name or "(no name)",
                        line.id,
                        line.product_id.id,
                        route.id,
                    )
                except Exception as e:
                    _logger.warning(
                        "[MXM_ROUTE_FALLBACK] failed order_id=%s line_id=%s: %s",
                        order.id,
                        line.id,
                        e,
                    )

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        for order in orders:
            order.sudo()._mxm_set_status("received", source="system")
            order._mxm_ensure_delivery_routes_for_mobile()
        return orders

    def write(self, vals):
        if "state" not in vals:
            return super().write(vals)
        new_state = vals["state"]
        for order in self:
            prev_state = order.state
            if prev_state == new_state:
                continue
            if new_state == "sale":
                # Confirmed -> set received if not already (idempotent)
                order.sudo()._mxm_set_status("received", source="system")
            elif new_state == "cancel":
                order.sudo()._mxm_set_status("cancelled", source="system")
            # done: do not auto-set delivered here; picking validation uses policy constant (stock_picking)
        return super().write(vals)
