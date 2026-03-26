# -*- coding: utf-8 -*-
"""
POS session: RPC methods for loan list and repayment.
All messages returned to POS are in Mongolian (MN only).
"""
from odoo import models
from odoo.exceptions import ValidationError


class PosSession(models.Model):
    _inherit = "pos.session"

    def get_credit_loans(self, partner_id):
        """
        Return list of open/partial loans for partner in this session's warehouse.
        For POS UI; labels in Mongolian.
        """
        self.ensure_one()
        warehouse_id = self.config_id.warehouse_id.id if self.config_id.warehouse_id else None
        if not warehouse_id or not partner_id:
            return []
        Loan = self.env["inguumel.credit.loan"].sudo()
        loans = Loan.search([
            ("warehouse_id", "=", warehouse_id),
            ("partner_id", "=", int(partner_id)),
            ("state", "in", ("open", "partial")),
        ], order="date_due asc", limit=50)
        state_labels = {
            "open": "Нээлттэй",
            "partial": "Хэсэгчлэн төлөгдсөн",
        }
        return [{
            "id": l.id,
            "name": l.name,
            "amount_total": l.amount_total,
            "amount_paid": l.amount_paid,
            "amount_residual": l.amount_residual,
            "date_due": str(l.date_due) if l.date_due else None,
            "state": l.state,
            "state_label": state_labels.get(l.state, l.state),
            "is_overdue": l.is_overdue,
        } for l in loans]

    def register_credit_repayment(self, loan_id, amount, date=None):
        """
        Register a repayment from POS. Raises ValidationError with MN message.
        """
        self.ensure_one()
        if not date:
            from odoo import fields as f
            date = f.Date.context_today(self)
        Loan = self.env["inguumel.credit.loan"].sudo()
        Repayment = self.env["inguumel.credit.repayment"].sudo()
        loan = Loan.browse(int(loan_id)).exists()
        if not loan:
            raise ValidationError("Зээл олдсонгүй.")
        if loan.state == "cancelled":
            raise ValidationError("Энэ зээлийг дахин төлөх боломжгүй.")
        if loan.state == "paid":
            raise ValidationError("Зээл бүрэн төлөгдсөн байна.")
        amount = float(amount)
        if amount <= 0:
            raise ValidationError("Төлөх дүн заавал оруулна уу")
        if amount > loan.amount_residual:
            raise ValidationError("Үлдэгдлээс их дүн оруулах боломжгүй")
        Repayment.create({
            "loan_id": loan.id,
            "amount": amount,
            "date": date,
            "source": "pos",
        })
        return True
