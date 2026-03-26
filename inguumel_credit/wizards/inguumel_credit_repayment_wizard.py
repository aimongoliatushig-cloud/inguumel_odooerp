# -*- coding: utf-8 -*-
"""
Wizard to register a repayment (partial payment) for a loan.
UI labels hardcoded in Mongolian (MN_ONLY).
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class InguumelCreditRepaymentWizard(models.TransientModel):
    _name = "inguumel.credit.repayment.wizard"
    _description = "Зээлийн төлөлт бүртгэх"

    loan_id = fields.Many2one(
        "inguumel.credit.loan",
        string="Зээл",
        required=True,
        ondelete="cascade",
        readonly=True,
    )
    amount = fields.Monetary(
        "Төлөх дүн",
        currency_field="currency_id",
        required=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="loan_id.currency_id",
    )
    date = fields.Date(
        "Төлсөн огноо",
        required=True,
        default=fields.Date.context_today,
    )
    notes = fields.Text("Тайлбар")
    post_to_accounting = fields.Boolean(
        "Нягтлан бодох бүртгэлд бүртгэх",
        default=False,
    )

    @api.constrains("amount")
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError("Төлөх дүн заавал оруулна уу (эерэг).")

    @api.constrains("amount", "loan_id")
    def _check_amount_not_exceed_residual(self):
        for rec in self:
            if not rec.loan_id or rec.loan_id.state == "cancelled":
                continue
            if rec.amount > rec.loan_id.amount_residual:
                raise ValidationError(
                    "Үлдэгдлээс их дүн оруулах боломжгүй."
                )

    def action_confirm(self):
        self.ensure_one()
        self.loan_id.env["inguumel.credit.repayment"].create({
            "loan_id": self.loan_id.id,
            "amount": self.amount,
            "date": self.date,
            "notes": self.notes,
            "source": "backoffice",
        })
        return {"type": "ir.actions.act_window_close"}
