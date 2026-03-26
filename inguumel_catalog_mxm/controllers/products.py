# -*- coding: utf-8 -*-
"""
GET /api/v1/mxm/products – warehouse-scoped product listing; only products with stock in warehouse.
"""
import logging

from odoo import http

from odoo.addons.inguumel_mobile_api.controllers.base import (
    get_request_id,
    ok,
    fail,
)

_logger = logging.getLogger(__name__)


class CatalogProductsAPI(http.Controller):
    """MXM catalog products endpoint."""

    @http.route(
        "/api/v1/mxm/products",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def products(self, warehouse_id=None, search=None, page=1, limit=20, category_id=None, **kwargs):
        """GET /api/v1/mxm/products – list only products available in the warehouse; optional category_id filter (child_of)."""
        request_id = get_request_id()
        try:
            _logger.info(
                "mxm.products called",
                extra={"request_id": request_id, "warehouse_id": warehouse_id, "category_id": category_id},
            )
            env = http.request.env
            warehouse = None
            if warehouse_id is not None and warehouse_id != "":
                try:
                    wh_id = int(warehouse_id)
                    Warehouse = env["stock.warehouse"].sudo()
                    warehouse = Warehouse.browse(wh_id)
                    if not warehouse.exists():
                        warehouse = None
                except (TypeError, ValueError):
                    pass
            if warehouse is None:
                user = env.user
                if user and not user._is_public():
                    partner = user.partner_id
                    default_wh = getattr(partner, "x_default_warehouse_id", None)
                    if default_wh:
                        warehouse = default_wh
                    if warehouse is None:
                        sum_rec = getattr(partner, "x_sum_id", None)
                        if sum_rec and getattr(sum_rec, "id", None):
                            Warehouse = env["stock.warehouse"].sudo()
                            warehouse = Warehouse.search(
                                [("x_sum_id", "=", sum_rec.id)],
                                limit=1,
                            )
            if warehouse is None or not warehouse.exists():
                _logger.info(
                    "mxm.products no warehouse partner_id=%s request_id=%s",
                    env.user.partner_id.id if env.user and not env.user._is_public() else None,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail(
                    message="Set your location first (aimag/sum) or provide warehouse_id.",
                    code="WAREHOUSE_NOT_SET",
                    http_status=400,
                    request_id=request_id,
                )
            warehouse = warehouse.sudo()
            loc = warehouse.lot_stock_id
            if not loc:
                _logger.warning(
                    "mxm.products warehouse has no lot_stock_id warehouse_id=%s request_id=%s",
                    warehouse.id,
                    request_id,
                    extra={"request_id": request_id},
                )
                return fail(
                    message="Warehouse has no stock location configured.",
                    code="WAREHOUSE_INVALID",
                    http_status=400,
                    request_id=request_id,
                )
            partner_id = env.user.partner_id.id if env.user and not env.user._is_public() else None
            sum_id = None
            if env.user and not env.user._is_public():
                sum_rec = getattr(env.user.partner_id, "x_sum_id", None)
                if sum_rec:
                    sum_id = sum_rec.id
            _logger.info(
                "mxm.products resolved partner_id=%s sum_id=%s warehouse_id=%s lot_stock_id=%s request_id=%s",
                partner_id,
                sum_id,
                warehouse.id,
                loc.id,
                request_id,
                extra={"request_id": request_id},
            )

            # Product IDs with available stock in this warehouse (lot_stock_id and children)
            Quant = env["stock.quant"].sudo()
            quants = Quant.search([
                ("location_id", "child_of", loc.id),
                ("quantity", ">", 0),
            ])
            product_ids_with_stock = set()
            for q in quants:
                available = (q.quantity or 0) - (q.reserved_quantity or 0)
                if available > 0:
                    product_ids_with_stock.add(q.product_id.id)
            product_ids_with_stock = list(product_ids_with_stock)

            domain = [
                ("active", "=", True),
                ("sale_ok", "=", True),
                ("id", "in", product_ids_with_stock),
            ]
            if search and search.strip():
                domain.append(("display_name", "ilike", search.strip()))
            if category_id is not None and category_id != "":
                try:
                    cat_id = int(category_id)
                    Category = env["product.category"].sudo()
                    cat = Category.browse(cat_id)
                    if cat.exists():
                        domain.append(("categ_id", "child_of", cat_id))
                except (TypeError, ValueError):
                    pass

            try:
                page = int(page) if page else 1
                limit = int(limit) if limit else 20
            except (TypeError, ValueError):
                page = 1
                limit = 20
            page = max(1, page)
            limit = min(max(1, limit), 100)

            Product = env["product.product"].sudo()
            products_all = Product.search(domain, order="id")
            total_count = len(products_all)
            offset = (page - 1) * limit
            products_page = products_all[offset : offset + limit]

            # Stock quantities per product in this warehouse (lot_stock_id and children)
            # qty_on_hand = physical; qty_reserved = reserved; qty_free = on_hand - reserved (available to promise)
            # available_qty MUST equal qty_free (branch visibility for mobile / prevent oversell)
            quants = env["stock.quant"].sudo().read_group(
                [
                    ("location_id", "child_of", loc.id),
                    ("product_id", "in", products_page.ids),
                ],
                ["quantity:sum", "reserved_quantity:sum"],
                ["product_id"],
            )
            qty_on_hand_by_product = {}
            qty_reserved_by_product = {}
            for q in quants:
                pid = q["product_id"][0]
                on_hand = q["quantity"] or 0
                reserved = q["reserved_quantity"] or 0
                qty_on_hand_by_product[pid] = on_hand
                qty_reserved_by_product[pid] = reserved
            qty_free_by_product = {
                pid: qty_on_hand_by_product.get(pid, 0) - qty_reserved_by_product.get(pid, 0)
                for pid in products_page.ids
            }
            # qty_forecast (virtual_available) with warehouse context
            Product = env["product.product"].sudo().with_context(warehouse_id=warehouse.id)
            products_with_ctx = Product.browse(products_page.ids)
            qty_forecast_by_product = {
                p.id: getattr(p, "virtual_available", 0) for p in products_with_ctx
            }

            def _has_image(prod):
                return bool(
                    getattr(prod, "image_1920", None)
                    or getattr(prod, "image_512", None)
                    or getattr(prod, "image_1024", None)
                )

            # Prefetch category info for all products (avoid N+1)
            unique_categ_ids = set()
            for product in products_page:
                if product.categ_id:
                    unique_categ_ids.add(product.categ_id.id)
            path_by_categ_id = {}
            name_by_categ_id = {}
            if unique_categ_ids:
                categories = env["product.category"].sudo().browse(list(unique_categ_ids))
                for cat in categories:
                    if cat.exists():
                        path_by_categ_id[cat.id] = getattr(cat, "complete_name", None) or cat.name
                        name_by_categ_id[cat.id] = cat.name

            data = []
            for product in products_page:
                write_date_str = product.write_date.isoformat() if product.write_date else ""
                image_url = None
                if _has_image(product):
                    image_url = "/api/v1/mxm/product-image/%s?size=1024&v=%s" % (
                        product.id,
                        write_date_str,
                    )
                cid = product.categ_id.id if product.categ_id else None
                category_name = name_by_categ_id.get(cid) if cid else None
                category_path = path_by_categ_id.get(cid) if cid else None
                qty_free = qty_free_by_product.get(product.id, 0)
                data.append({
                    "id": product.id,
                    "name": product.display_name,
                    "price": product.lst_price,
                    "barcode": product.barcode or None,
                    "write_date": write_date_str,
                    "image_url": image_url,
                    "qty_on_hand": qty_on_hand_by_product.get(product.id, 0),
                    "qty_reserved": qty_reserved_by_product.get(product.id, 0),
                    "qty_free": qty_free,
                    "qty_forecast": qty_forecast_by_product.get(product.id, 0),
                    "available_qty": qty_free,  # MUST equal qty_free (available to promise)
                    "category_id": cid,
                    "category_name": category_name,
                    "category_path": category_path,
                })

            has_next = (offset + limit) < total_count
            meta = {
                "page": page,
                "limit": limit,
                "count": total_count,
                "has_next": has_next,
            }
            return ok(data=data, meta=meta, request_id=request_id)
        except Exception as e:
            _logger.exception(
                "mxm.products error: %s",
                e,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="SERVER_ERROR",
                http_status=500,
                request_id=request_id,
            )
