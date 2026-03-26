# -*- coding: utf-8 -*-
"""
Business logic for loan and repayment. Used by controllers only.
No UI; messages returned are in Mongolian for API responses.
"""
from odoo import fields, models
from odoo.exceptions import ValidationError


class LoanService(models.AbstractModel):
    _name = "inguumel.credit.loan.service"
    _description = "Loan service (business logic)"

    def loan_list(self, warehouse_id=None, partner_id=None, limit=50, offset=0):
        """Return loan records for list API. limit capped at 50."""
        limit = min(int(limit), 50) if limit else 50
        offset = max(0, int(offset))
        domain = [("state", "!=", "cancelled")]
        if warehouse_id:
            domain.append(("warehouse_id", "=", int(warehouse_id)))
        if partner_id:
            domain.append(("partner_id", "=", int(partner_id)))
        return self.env["inguumel.credit.loan"].search(
            domain, order="create_date desc", limit=limit, offset=offset
        )

    def loan_get(self, loan_id):
        """Return one loan by id or None."""
        return self.env["inguumel.credit.loan"].browse(int(loan_id)).exists()

    def repayment_register(self, loan_id, amount, date=None, notes=None, source="api"):
        """
        Register a repayment for a loan. Raises ValidationError with MN message on failure.
        Returns the created repayment record.
        """
        Loan = self.env["inguumel.credit.loan"]
        Repayment = self.env["inguumel.credit.repayment"]
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
            raise ValidationError("Үлдэгдэл дүнгээс их төлөх боломжгүй.")
        vals = {
            "loan_id": loan.id,
            "amount": amount,
            "date": date or fields.Date.context_today(self),
            "notes": notes or "",
            "source": source,
        }
        return Repayment.create(vals)
