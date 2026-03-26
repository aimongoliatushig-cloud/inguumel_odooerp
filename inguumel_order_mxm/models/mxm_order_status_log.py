# -*- coding: utf-8 -*-
"""Canonical timeline log per sale.order for mobile Order Detail UI."""
from odoo import api, fields, models

# Canonical status codes (lowercase snake_case) – single source of truth for API and UI
MXM_DELIVERY_STATUS_CODES = [
    ("received", "Received"),
    ("preparing", "Preparing"),
    ("prepared", "Prepared"),
    ("out_for_delivery", "Out for Delivery"),
    ("delivered", "Delivered"),
    ("cancelled", "Cancelled"),
]

STATUS_LABELS_MN = {
    "received": "Захиалга авлаа",
    "preparing": "Бэлтгэж байна",
    "prepared": "Бэлтгэж дууссан",
    "out_for_delivery": "Хүргэлтэд гарсан",
    "delivered": "Хүргэгдсэн",
    "cancelled": "Цуцлагдсан",
    "cod_confirmed": "COD баталгаажсан",
}


class MxmOrderStatusLog(models.Model):
    _name = "mxm.order.status.log"
    _description = "MXM Order Status Log (timeline)"
    _order = "at asc, id asc"

    order_id = fields.Many2one(
        "sale.order",
        string="Order",
        required=True,
        ondelete="cascade",
        index=True,
    )
    code = fields.Selection(
        selection=MXM_DELIVERY_STATUS_CODES + [("cod_confirmed", "COD Confirmed")],
        string="Status Code",
        required=True,
        index=True,
    )
    at = fields.Datetime(string="At", required=True, default=fields.Datetime.now, index=True)
    user_id = fields.Many2one("res.users", string="User", ondelete="set null")
    note = fields.Text(string="Note")
    source = fields.Selection(
        selection=[
            ("system", "System"),
            ("staff", "Staff"),
            ("courier", "Courier"),
            ("customer", "Customer"),
            ("mobile_owner", "Mobile Owner"),
            ("drive_app", "Drive App"),
            ("driver", "Driver"),
        ],
        string="Source",
    )
    source_model = fields.Char(string="Source Model", index=True, help="Optional: e.g. stock.picking")
    source_id = fields.Integer(string="Source ID", help="Optional: ID of source record")
    # Display fields for ERP audit table
    label_mn = fields.Char(string="Label (MN)", compute="_compute_label_mn", store=False)
    at_hhmm = fields.Char(string="Time", compute="_compute_at_hhmm", store=False)
    # is_last: from order's logs by (at desc); no dependency on self.id
    is_last = fields.Boolean(compute="_compute_is_last", store=False)
    display_line = fields.Char(string="Step", compute="_compute_display_line", store=False)

    @api.depends("code")
    def _compute_label_mn(self):
        for log in self:
            log.label_mn = STATUS_LABELS_MN.get(log.code, log.code or "")

    @api.depends("at")
    def _compute_at_hhmm(self):
        for log in self:
            log.at_hhmm = log.at.strftime("%H:%M") if log.at else ""

    # No @api.depends('id') – is_last derived from sibling logs and at only
    @api.depends("order_id", "order_id.mxm_status_log_ids", "order_id.mxm_status_log_ids.at", "at")
    def _compute_is_last(self):
        for log in self:
            order = log.order_id
            if not order or not order.mxm_status_log_ids:
                log.is_last = False
                continue
            last = order.mxm_status_log_ids.sorted("at", reverse=True)[:1]
            log.is_last = log in last

    @api.depends("label_mn", "is_last")
    def _compute_display_line(self):
        for log in self:
            marker = "●" if log.is_last else "✓"
            log.display_line = f"{marker} {log.label_mn}" if log.label_mn else ""

    LEGACY_MIGRATED_KEY = "mxm.delivery.legacy_migrated"
    LEGACY_BATCH_SIZE = 500

    @api.model
    def _migrate_legacy_codes(self):
        """
        One-time: update old codes (RECEIVED, PACKED, etc.) to canonical lowercase.
        Uses ir.config_parameter 'mxm.delivery.legacy_migrated'; if already true, no-op.
        Batch-safe for large DBs. Call from shell: env['mxm.order.status.log']._migrate_legacy_codes().
        """
        ICP = self.env["ir.config_parameter"].sudo()
        if ICP.get_param(self.LEGACY_MIGRATED_KEY, "false").lower() in ("true", "1"):
            return
        OLD_TO_NEW = {
            "RECEIVED": "received",
            "PREPARING": "preparing",
            "PACKED": "prepared",
            "OUT_FOR_DELIVERY": "out_for_delivery",
            "DELIVERED": "delivered",
            "CANCELLED": "cancelled",
        }
        Log = self.sudo()
        for old, new in OLD_TO_NEW.items():
            while True:
                batch = Log.search([("code", "=", old)], limit=self.LEGACY_BATCH_SIZE)
                if not batch:
                    break
                batch.write({"code": new})
        # Sync sale.order.mxm_delivery_status from last log where missing (batched)
        SaleOrder = self.env["sale.order"].sudo()
        while True:
            orders = SaleOrder.search([
                ("mxm_delivery_status", "=", False),
                ("mxm_status_log_ids", "!=", False),
            ], limit=self.LEGACY_BATCH_SIZE)
            if not orders:
                break
            for order in orders:
                last = order.mxm_status_log_ids.sorted("at", reverse=True)[:1]
                if last and last.code:
                    order.write({"mxm_delivery_status": last.code})
        ICP.set_param(self.LEGACY_MIGRATED_KEY, "true")
