# -*- coding: utf-8 -*-
{
    "name": "Inguumel Mobile API Core",
    "version": "1.0.3",
    "depends": ["base", "web", "stock", "ingoo_location_mxm"],
    "pre_init_hook": "pre_init_hook",
    "post_init_hook": "post_init_hook",
    "data": [
        "security/ir.model.access.csv",
        "views/stock_warehouse_views.xml",
    ],
    "installable": True,
    "application": False,
}
