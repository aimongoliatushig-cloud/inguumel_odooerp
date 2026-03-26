# -*- coding: utf-8 -*-
"""
Loan request (mobile approval workflow).
UI labels hardcoded in Mongolian (MN_ONLY).
"""
from odoo import api, fields, models


class InguumelCreditRequest(models.Model):
    _name = "inguumel.credit.request"
    _description = "Зээлийн хүсэлт"
    _order = "create_date desc"

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
    amount_requested = fields.Monetary(
        "Хүссэн дүн",
        currency_field="currency_id",
        required=True,
    )
    amount_approved = fields.Monetary(
        "Зөвшөөрсөн дүн",
        currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    date_due = fields.Date("Төлөх огноо")
    reason = fields.Text("Шалтгаан")
    state = fields.Selection(
        [
            ("draft", "Ноорог"),
            ("approved", "Зөвшөөрсөн"),
            ("rejected", "Татгалзсан"),
        ],
        string="Төлөв",
        default="draft",
        required=True,
        copy=False,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Шийдвэрлэсэн хэрэглэгч",
    )
    loan_id = fields.Many2one(
        "inguumel.credit.loan",
        string="Үүсгэсэн зээл",
        copy=False,
    )

    def action_approve(self):
        self.write({"state": "approved", "user_id": self.env.user.id})

    def action_reject(self):
        self.write({"state": "rejected", "user_id": self.env.user.id})
