# -*- coding: utf-8 -*-
{
    "name": "Inguumel Lucky Wheel",
    "version": "1.0.0",
    "author": "Inguumel",
    "description": "Lucky Wheel (Lucky Draw) for Odoo 19. Spend accumulation, spins, prizes, OTP redemption.",
    "license": "LGPL-3",
    "depends": [
        "base",
        "sale_stock",
        "stock",
        "inguumel_mobile_api",
        "inguumel_order_mxm",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/cron_data.xml",
        "data/config_parameter_data.xml",
        "views/lucky_wheel_config_views.xml",
        "views/lucky_wheel_node_views.xml",
        "views/lucky_wheel_spend_views.xml",
        "views/lucky_wheel_prize_views.xml",
        "views/lucky_wheel_dashboard_views.xml",
        "views/lucky_wheel_actions.xml",
        "views/lucky_wheel_menu.xml",
    ],
    "installable": True,
    "application": False,
}
