# -*- coding: utf-8 -*-
{
    "name": "Ингүүмэл Зээл POS",
    "version": "1.0.0",
    "depends": ["point_of_sale", "inguumel_credit"],
    "data": [
        "views/pos_config_views.xml",
    ],
    # POS frontend (Зээл төлөлт button) disabled to avoid freeze; use backoffice for loan repayment.
    # "assets": {
    #     "point_of_sale._assets_pos": [
    #         "inguumel_credit_pos/static/src/**/*.js",
    #         "inguumel_credit_pos/static/src/**/*.xml",
    #     ],
    # },
    "installable": True,
    "application": False,
}
