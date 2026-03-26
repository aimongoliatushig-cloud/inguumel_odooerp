# -*- coding: utf-8 -*-
"""Link stock.picking (WH/OUT) to MXM canonical flow: received → preparing → prepared → out_for_delivery → delivered."""
import json
import logging
import time
import traceback
from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Policy: when picking is validated (state=done), set order delivery status to delivered (only if current is out_for_delivery).
# Decoupled from UI: "Хүргэгдсэн" button does NOT validate picking. Set False to keep picking done separate from "delivered".
PICKING_DONE_MEANS_DELIVERED = True

# Policy: when staff sets status to out_for_delivery, optionally validate the picking (state=done).
# Default False to protect inventory integrity: delivery status and stock moves are independent.
PICKING_VALIDATE_ON_OUT_FOR_DELIVERY = False

# #region agent log
_DEBUG_LOG_PATH = "/opt/odoo/custom_addons/.cursor/debug.log"
_DEBUG_LOG_FALLBACK = "/tmp/odoo_debug_cursor.log"
def _debug_log(location, message, data=None, hypothesis_id=None):
    payload = json.dumps({"location": location, "message": message, "data": data or {}, "hypothesisId": hypothesis_id, "timestamp": int(time.time() * 1000), "sessionId": "debug-session", "runId": "run1"}) + "\n"
    for path in (_DEBUG_LOG_PATH, _DEBUG_LOG_FALLBACK):
        try:
            with open(path, "a") as f:
                f.write(payload)
            break
        except Exception:
            continue
# #endregion

# Canonical codes (lowercase) – same as sale.order / mxm.order.status.log
STATUS_LABELS_MN = {
    "received": "Захиалга авлаа",
    "preparing": "Бэлтгэж байна",
    "prepared": "Бэлтгэж дууссан",
    "out_for_delivery": "Хүргэлтэд гарсан",
    "delivered": "Хүргэгдсэн",
    "cancelled": "Цуцлагдсан",
}

# Timeline order (excluding cancelled)
MXM_TIMELINE_CODES = ["received", "preparing", "prepared", "out_for_delivery", "delivered"]

_MXM_NO_ORDER_MSG = (
    "Энэ хүргэлт нь захиалгатай холбоогүй эсвэл гаргах төрөл биш тул шат өөрчлөх боломжгүй."
)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    picking_type_code = fields.Selection(
        related="picking_type_id.code",
        string="Picking Type Code",
        readonly=True,
        store=False,
    )
    # Stored link to sale order for MXM (outgoing only); enables stored related status fields for search
    mxm_sale_order_id = fields.Many2one(
        "sale.order",
        string="MXM Sale Order",
        compute="_compute_mxm_sale_order_id",
        store=True,
        readonly=True,
        index=True,
    )
    mxm_order_last_status_code = fields.Char(
        related="mxm_sale_order_id.mxm_last_status_code",
        string="MXM Order Last Status Code",
        store=True,
        readonly=True,
        index=True,
    )
    mxm_order_last_status_label_mn = fields.Char(
        related="mxm_sale_order_id.mxm_last_status_label_mn",
        string="Захиалгын шат (MN)",
        store=True,
        readonly=True,
        index=True,
    )
    mxm_order_status_log_ids = fields.One2many(
        related="mxm_sale_order_id.mxm_status_log_ids",
        string="MXM Status History",
        readonly=True,
    )
    mxm_next_action_label = fields.Char(
        string="Дараагийн үйлдэл",
        compute="_compute_mxm_next_action",
        store=False,
    )
    mxm_next_action_help = fields.Text(
        string="Дараагийн алхам заавар",
        compute="_compute_mxm_next_action",
        store=False,
    )
    mxm_timeline_json = fields.Text(
        string="MXM Timeline JSON",
        compute="_compute_mxm_timeline_json",
        store=False,
    )
    mxm_timeline_html = fields.Html(
        string="MXM Timeline",
        compute="_compute_mxm_timeline_html",
        store=False,
        sanitize=True,
    )

    def _mxm_is_outgoing_with_order(self):
        """True only when picking type is outgoing AND we have a linked sale order (mxm_sale_order_id)."""
        self.ensure_one()
        if not self.picking_type_id:
            return False
        if getattr(self.picking_type_id, "code", None) != "outgoing":
            return False
        if not self.mxm_sale_order_id:
            return False
        return True

    @api.depends("mxm_order_last_status_code", "mxm_sale_order_id", "picking_type_id", "picking_type_id.code")
    def _compute_mxm_next_action(self):
        help_texts = {
            "received": "Барааг түүж бэлтгэж эхэл. Бэлтгэл эхэлсэн бол 'Бэлтгэж байна' дар.",
            "preparing": "Бараа бүрэн болсон бол 'Бэлтгэж дууссан' дар.",
            "prepared": "Курьерт өгч гаргасан бол 'Хүргэлтэд гарсан' дар.",
            "out_for_delivery": "Хэрэглэгч хүлээн авсан бол 'Хүргэгдсэн' дар.",
            "delivered": "Энэ захиалга дууссан.",
        }
        button_labels = {
            "received": "Бэлтгэж байна",
            "preparing": "Бэлтгэж дууссан",
            "prepared": "Хүргэлтэд гарсан",
            "out_for_delivery": "Хүргэгдсэн",
            "delivered": "",
        }
        for picking in self:
            if not picking._mxm_is_outgoing_with_order():
                picking.mxm_next_action_label = False
                picking.mxm_next_action_help = False
                continue
            code = picking.mxm_order_last_status_code or "received"
            picking.mxm_next_action_label = button_labels.get(code, "")
            picking.mxm_next_action_help = help_texts.get(code, "Энэ захиалга дууссан.")

    def _mxm_timeline_nodes(self):
        """Build 5-step timeline: list of dicts {code, label, state: done|active|todo, time}. Defensive: never assume sale_id or log.at exists."""
        self.ensure_one()
        if not self._mxm_is_outgoing_with_order():
            return []
        order = self.mxm_sale_order_id
        if not order:
            return []
        try:
            logs = getattr(order, "mxm_status_log_ids", self.env["mxm.order.status.log"])
            if not logs:
                logs = self.env["mxm.order.status.log"]
            else:
                logs = logs.sorted("at")
        except Exception:
            return []
        last_code = getattr(order, "mxm_delivery_status", None) or getattr(order, "mxm_last_status_code", None) or None
        code_to_time = {}
        for log in logs:
            try:
                if getattr(log, "code", None) not in MXM_TIMELINE_CODES:
                    continue
                at_val = getattr(log, "at", None)
                code_to_time[log.code] = at_val.strftime("%H:%M") if at_val else ""
            except Exception:
                code_to_time[getattr(log, "code", "")] = ""
        nodes = []
        for code in MXM_TIMELINE_CODES:
            label = STATUS_LABELS_MN.get(code, code)
            time_str = code_to_time.get(code, "")
            if last_code == code:
                state = "active"
            elif code in code_to_time:
                state = "done"
            else:
                state = "todo"
            nodes.append({
                "code": code,
                "label": label,
                "state": state,
                "time": time_str,
            })
        return nodes

    @api.depends("mxm_sale_order_id", "mxm_sale_order_id.mxm_status_log_ids", "mxm_sale_order_id.mxm_last_status_code", "picking_type_id", "picking_type_id.code")
    def _compute_mxm_timeline_json(self):
        for picking in self:
            if not picking._mxm_is_outgoing_with_order():
                picking.mxm_timeline_json = "[]"
                continue
            try:
                nodes = picking._mxm_timeline_nodes()
                picking.mxm_timeline_json = json.dumps(nodes, ensure_ascii=False) if nodes else "[]"
            except Exception:
                picking.mxm_timeline_json = "[]"

    @api.depends("mxm_sale_order_id", "mxm_sale_order_id.mxm_status_log_ids", "mxm_sale_order_id.mxm_last_status_code", "picking_type_id", "picking_type_id.code")
    def _compute_mxm_timeline_html(self):
        # #region agent log
        _debug_log("stock_picking._compute_mxm_timeline_html:entry", "compute entry", {"picking_ids": list(self.ids)}, "H1")
        # #endregion
        _safe_error_html = "<div class=\"text-danger\">Timeline error</div>"
        for picking in self:
            if not picking._mxm_is_outgoing_with_order():
                picking.mxm_timeline_html = False
                continue
            try:
                nodes = picking._mxm_timeline_nodes()
                if not nodes:
                    picking.mxm_timeline_html = False
                    continue
                parts = []
                for node in nodes:
                    state = node.get("state", "todo")
                    label = node.get("label", "")
                    time_str = node.get("time") or ""
                    if state == "done":
                        icon = "<span class=\"text-success\">✓</span>"
                        cls = "text-success"
                    elif state == "active":
                        icon = "<span class=\"text-primary fw-bold\">●</span>"
                        cls = "text-primary fw-bold"
                    else:
                        icon = "<span class=\"text-muted\">○</span>"
                        cls = "text-muted"
                    time_span = " <small class=\"text-muted\">{}</small>".format(time_str) if time_str else ""
                    parts.append(
                        "<span class=\"mx-2 {}\">{} {}{}</span>".format(cls, icon, label, time_span)
                    )
                picking.mxm_timeline_html = (
                    "<div class=\"d-flex flex-wrap align-items-center justify-content-between border rounded p-2 mb-2\">"
                    + " ".join(parts)
                    + "</div>"
                )
            except Exception as e:
                # #region agent log
                _debug_log("stock_picking._compute_mxm_timeline_html:except", "compute exception", {"picking_id": picking.id, "error": str(e), "traceback": traceback.format_exc()}, "H1")
                # #endregion
                _logger.exception("MXM timeline compute failed for picking %s", picking.id)
                picking.mxm_timeline_html = _safe_error_html

    @api.depends("picking_type_id", "picking_type_id.code", "sale_id", "origin")
    def _compute_mxm_sale_order_id(self):
        # #region agent log
        _debug_log("stock_picking._compute_mxm_sale_order_id:entry", "compute sale_order entry", {"picking_ids": list(self.ids)}, "H5")
        # #endregion
        for picking in self:
            if not picking.picking_type_id or picking.picking_type_id.code != "outgoing":
                picking.mxm_sale_order_id = False
                continue
            if picking.sale_id:
                picking.mxm_sale_order_id = picking.sale_id
                continue
            if picking.origin:
                order = self.env["sale.order"].search([("name", "=", picking.origin)], limit=1)
                picking.mxm_sale_order_id = order if order else False
            else:
                picking.mxm_sale_order_id = False

    mxm_status_timeline_display = fields.Text(
        string="Status Timeline",
        compute="_compute_mxm_status_timeline_display",
        store=False,
        help="Readonly timeline from sale order status history (outgoing only).",
    )

    @api.depends("mxm_sale_order_id", "mxm_sale_order_id.mxm_status_log_ids", "mxm_sale_order_id.mxm_status_log_ids.code", "mxm_sale_order_id.mxm_status_log_ids.at", "mxm_sale_order_id.create_date", "create_date", "picking_type_id", "picking_type_id.code")
    def _compute_mxm_status_timeline_display(self):
        for picking in self:
            if not picking._mxm_is_outgoing_with_order() or not picking.mxm_sale_order_id:
                picking.mxm_status_timeline_display = ""
                continue
            try:
                order = picking.mxm_sale_order_id
                logs = getattr(order, "mxm_status_log_ids", self.env["mxm.order.status.log"])
                if not logs:
                    logs = self.env["mxm.order.status.log"]
                else:
                    logs = logs.sorted("at")
                if not logs:
                    at_dt = getattr(order, "create_date", None) or getattr(picking, "create_date", None)
                    at_str = at_dt.strftime("%H:%M") if at_dt else ""
                    picking.mxm_status_timeline_display = "● {} — {}".format(STATUS_LABELS_MN.get("received", "received"), at_str)
                    continue
                lines = []
                for i, log in enumerate(logs):
                    label = STATUS_LABELS_MN.get(getattr(log, "code", ""), getattr(log, "code", ""))
                    at_val = getattr(log, "at", None)
                    at_str = at_val.strftime("%H:%M") if at_val else ""
                    marker = "●" if i == len(logs) - 1 else "✓"
                    lines.append("{} {} — {}".format(marker, label, at_str))
                picking.mxm_status_timeline_display = "\n".join(lines)
            except Exception:
                _logger.exception("MXM status timeline display compute failed for picking %s", picking.id)
                picking.mxm_status_timeline_display = ""

    def _mxm_get_sale_order(self):
        """Return related sale.order for this picking (outgoing only); None if not linked."""
        self.ensure_one()
        return self.mxm_sale_order_id or self.env["sale.order"]

    def _mxm_ensure_outgoing_with_order(self):
        """Raise UserError in Mongolian if not outgoing or no sale order (for step buttons)."""
        for picking in self:
            if not picking.picking_type_id or picking.picking_type_id.code != "outgoing":
                raise UserError(_MXM_NO_ORDER_MSG)
            if not picking.mxm_sale_order_id:
                raise UserError(_MXM_NO_ORDER_MSG)

    def write(self, vals):
        if "state" not in vals:
            return super().write(vals)
        new_state = vals["state"]
        for picking in self:
            prev_state = picking.state
            if prev_state == new_state:
                continue
            order = picking._mxm_get_sale_order()
            if not order or not order.exists():
                continue
            # Optional: when picking is assigned (ready), set preparing only if current is received
            if new_state == "assigned":
                ok_, err_msg, error_code, stock_effect = order.sudo()._mxm_set_status(
                    "preparing",
                    source="system",
                    note="Picking %s ready" % (picking.name or ""),
                    source_model="stock.picking",
                    source_id=picking.id,
                )
                if not ok_:
                    pass  # transition not allowed (e.g. already past preparing), skip
            elif new_state == "done":
                # v1 policy: picking done -> set delivered only if current is out_for_delivery
                if PICKING_DONE_MEANS_DELIVERED and order.mxm_delivery_status == "out_for_delivery":
                    order.sudo()._mxm_set_status(
                        "delivered",
                        source="system",
                        note="Picking %s done" % (picking.name or ""),
                        source_model="stock.picking",
                        source_id=picking.id,
                    )
        return super().write(vals)

    def action_mxm_preparing(self):
        """Button 'Бэлтгэж байна': set status preparing (only when transition allowed)."""
        self._mxm_ensure_outgoing_with_order()
        for picking in self:
            order = picking._mxm_get_sale_order()
            ok, err_msg, error_code, stock_effect = order.sudo()._mxm_set_status(
                "preparing",
                source="staff",
                note="Set preparing from picking",
                source_model="stock.picking",
                source_id=picking.id,
            )
            if not ok:
                raise UserError(err_msg or _MXM_NO_ORDER_MSG)
        return True

    def action_mxm_prepared(self):
        """Button 'Бэлтгэж дууссан': set status prepared. Optionally assign picking if needed."""
        self._mxm_ensure_outgoing_with_order()
        for picking in self:
            if picking.state not in ("assigned",):
                picking.action_assign()
            order = picking._mxm_get_sale_order()
            ok, err_msg, error_code, stock_effect = order.sudo()._mxm_set_status(
                "prepared",
                source="staff",
                note="Packed via picking",
                source_model="stock.picking",
                source_id=picking.id,
            )
            if not ok:
                raise UserError(err_msg or _MXM_NO_ORDER_MSG)
        return True

    def action_mxm_out_for_delivery(self):
        """Button 'Хүргэлтэд гарсан': set status out_for_delivery. Optionally validate picking if policy enabled."""
        self._mxm_ensure_outgoing_with_order()
        for picking in self:
            order = picking._mxm_get_sale_order()
            ok, err_msg, error_code, stock_effect = order.sudo()._mxm_set_status(
                "out_for_delivery",
                source="staff",
                note="Picking %s out for delivery" % (picking.name or ""),
                source_model="stock.picking",
                source_id=picking.id,
            )
            if not ok:
                raise UserError(err_msg or _MXM_NO_ORDER_MSG)
        if PICKING_VALIDATE_ON_OUT_FOR_DELIVERY:
            return self.button_validate()
        return True

    def action_mxm_delivered(self):
        """Button 'Хүргэгдсэн': set status delivered only. Does NOT validate picking (inventory integrity)."""
        self._mxm_ensure_outgoing_with_order()
        for picking in self:
            order = picking._mxm_get_sale_order()
            ok, err_msg, error_code, stock_effect = order.sudo()._mxm_set_status(
                "delivered",
                source="staff",
                note="Marked delivered from picking",
                source_model="stock.picking",
                source_id=picking.id,
            )
            if not ok:
                raise UserError(err_msg or _MXM_NO_ORDER_MSG)
        return True
