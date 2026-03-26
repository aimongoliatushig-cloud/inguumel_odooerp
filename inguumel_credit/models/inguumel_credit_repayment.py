# -*- coding: utf-8 -*-
"""
Repayment (partial payment) ledger for loans.
UI labels hardcoded in Mongolian (MN_ONLY).
"""
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class InguumelCreditRepayment(models.Model):
    _name = "inguumel.credit.repayment"
    _description = "Төлөлт"
    _order = "date desc, id desc"

    loan_id = fields.Many2one(
        "inguumel.credit.loan",
        string="Зээл",
        required=True,
        ondelete="cascade",
        index=True,
    )
    amount = fields.Monetary(
        "Төлсөн дүн",
        currency_field="currency_id",
        required=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="loan_id.currency_id",
        store=True,
    )
    date = fields.Date("Төлсөн огноо", required=True, default=fields.Date.context_today)
    user_id = fields.Many2one(
        "res.users",
        string="Оруулсан хэрэглэгч",
        default=lambda self: self.env.user,
        required=True,
    )
    notes = fields.Text("Тайлбар")
    source = fields.Selection(
        [
            ("backoffice", "Эх сурвалж: Бэк оффис"),
            ("pos", "Эх сурвалж: POS"),
            ("api", "Эх сурвалж: API"),
        ],
        string="Эх сурвалж",
        default="backoffice",
        required=True,
    )

    @api.constrains("amount")
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError("Төлсөн дүн эерэг байх ёстой.")

    @api.constrains("amount", "loan_id")
    def _check_amount_not_exceed_residual(self):
        for rec in self:
            if not rec.loan_id or rec.loan_id.state == "cancelled":
                continue
            residual = rec.loan_id.amount_residual
            if rec.amount > residual:
                raise ValidationError(
                    "Үлдэгдэл дүнгээс их төлөх боломжгүй."
                )

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        recs.mapped("loan_id")._recompute_state()
        return recs

    def unlink(self):
        loans = self.mapped("loan_id")
        res = super().unlink()
        loans._recompute_state()
        return res
