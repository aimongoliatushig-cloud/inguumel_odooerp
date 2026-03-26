# -*- coding: utf-8 -*-
"""Aimag (province) model for MXM location hierarchy."""
from odoo import fields, models


class IngoLocationAimag(models.Model):
    _name = "ingo.location.aimag"
    _description = "Aimag (Province)"

    name = fields.Char(string="Name", required=True, index=True)
