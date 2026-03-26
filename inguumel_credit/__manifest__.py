# -*- coding: utf-8 -*-
{
    "name": "Ингүүмэл Зээл",
    "version": "1.0.0",
    "depends": ["sale", "stock", "account", "inguumel_mobile_api"],
    "data": [
        "security/ir.model.access.csv",
        "views/inguumel_credit_loan_views.xml",
        "views/inguumel_credit_repayment_views.xml",
        "views/inguumel_credit_request_views.xml",
        "views/inguumel_credit_actions.xml",
        "views/inguumel_credit_menus.xml",
        "wizards/inguumel_credit_repayment_wizard_views.xml",
    ],
    "installable": True,
    "application": False,
}
