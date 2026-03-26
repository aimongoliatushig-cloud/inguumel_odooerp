# -*- coding: utf-8 -*-
"""
Core loan model: branch loan with partial repayment ledger.
UI labels are hardcoded in Mongolian (MN_ONLY).
"""
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class InguumelCreditLoan(models.Model):
    _name = "inguumel.credit.loan"
    _description = "Зээл"
    _order = "create_date desc"

    name = fields.Char("Зээлийн дугаар", required=True, index=True, copy=False)
    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Салбар",
        required=True,
        ondelete="restrict",
        index=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Харилцагч",
        required=True,
        ondelete="restrict",
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Мөнгөний нэгж",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    amount_total = fields.Monetary(
        "Нийт дүн",
        currency_field="currency_id",
        required=True,
    )
    amount_paid = fields.Monetary(
        "Төлөгдсөн дүн",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
    )
    amount_residual = fields.Monetary(
        "Үлдэгдэл",
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
    )
    date_due = fields.Date("Төлөх огноо", required=True)
    state = fields.Selection(
        [
            ("open", "Нээлттэй"),
            ("partial", "Хэсэгчлэн төлөгдсөн"),
            ("paid", "Бүрэн төлөгдсөн"),
            ("cancelled", "Цуцлагдсан"),
        ],
        string="Төлөв",
        default="open",
        required=True,
        copy=False,
    )
    is_overdue = fields.Boolean(
        "Хугацаа хэтэрсэн",
        compute="_compute_is_overdue",
        store=True,
    )
    notes = fields.Text("Тайлбар")
    repayment_ids = fields.One2many(
        "inguumel.credit.repayment",
        "loan_id",
        string="Төлөлтүүд",
    )
    request_id = fields.Many2one(
        "inguumel.credit.request",
        string="Зээлийн хүсэлт",
        copy=False,
    )

    _sql_constraints = [
        ("name_uniq", "UNIQUE(name)", "Зээлийн дугаар давхардах боломжгүй."),
    ]

    @api.depends("repayment_ids.amount", "amount_total", "state")
    def _compute_amounts(self):
        for rec in self:
            if rec.state == "cancelled":
                rec.amount_paid = 0.0
                rec.amount_residual = rec.amount_total
                continue
            total_paid = sum(rec.repayment_ids.mapped("amount"))
            rec.amount_paid = total_paid
            rec.amount_residual = rec.amount_total - total_paid

    @api.depends("date_due", "state")
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = (
                rec.state in ("open", "partial")
                and rec.date_due
                and rec.date_due < today
            )

    def write(self, vals):
        res = super().write(vals)
        self._recompute_state()
        return res

    def _recompute_state(self):
        for rec in self:
            if rec.state == "cancelled":
                continue
            if rec.amount_paid >= rec.amount_total and rec.amount_total > 0:
                rec.state = "paid"
            elif rec.amount_paid > 0:
                rec.state = "partial"
            else:
                rec.state = "open"

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_add_repayment(self):
        """Төлөлт нэмэх wizard нээх (MN UI). No xmlid dependency."""
        self.ensure_one()
        if self.state in ("cancelled", "paid"):
            raise UserError("Энэ зээл дээр төлөлт нэмэх боломжгүй.")
        return {
            "type": "ir.actions.act_window",
            "name": "Зээлийн төлөлт бүртгэх",
            "res_model": "inguumel.credit.repayment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_loan_id": self.id,
                "default_amount": self.amount_residual or 0.0,
            },
        }

    @api.constrains("amount_total")
    def _check_amount_total_positive(self):
        for rec in self:
            if rec.amount_total <= 0:
                raise ValidationError("Нийт дүн эерэг байх ёстой.")
