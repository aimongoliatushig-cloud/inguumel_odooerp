# -*- coding: utf-8 -*-
{
    "name": "Inguumel Order MXM",
    "version": "1.1.0",
    "author": "Inguumel",
    "license": "LGPL-3",
    "depends": ["base", "sale_stock", "inguumel_mobile_api", "inguumel_cart_mxm"],
    "data": [
        "data/config_parameter_cod_auto_paid.xml",
        "data/config_parameter_cash_confirm.xml",
        "data/cron_cod_auto_paid.xml",
        "security/res_groups.xml",
        "security/ir.model.access.csv",
        "views/delivery_dashboard_views.xml",
        "views/res_users_views.xml",
        "views/stock_picking_views.xml",
        "views/sale_order_views.xml",
    ],
    "installable": True,
    "application": False,
}
