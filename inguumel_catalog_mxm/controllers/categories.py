# -*- coding: utf-8 -*-
"""
GET /api/v1/mxm/categories – list product categories (optional warehouse filter).
Requires session cookie; optional warehouse_id to limit to categories with stock.
"""
import logging

from odoo import http

from odoo.addons.inguumel_mobile_api.controllers.base import (
    get_request_id,
    ok,
    fail,
)

_logger = logging.getLogger(__name__)


def _require_user(request_id):
    """Return 401 if public user."""
    user = http.request.env.user
    if not user or user._is_public():
        return None, fail(
            message="Unauthorized",
            code="UNAUTHORIZED",
            http_status=401,
            request_id=request_id,
        )
    return user, None


def _product_ids_with_stock_in_warehouse(env, warehouse):
    """Return list of product IDs that have available qty in warehouse (lot_stock_id and children)."""
    loc = warehouse.lot_stock_id
    if not loc:
        return []
    Quant = env["stock.quant"].sudo()
    quants = Quant.search([
        ("location_id", "child_of", loc.id),
        ("quantity", ">", 0),
    ])
    product_ids = set()
    for q in quants:
        available = (q.quantity or 0) - (q.reserved_quantity or 0)
        if available > 0:
            product_ids.add(q.product_id.id)
    return list(product_ids)


def _category_ids_with_ancestors(env, category_ids):
    """Given set of category IDs, return set including all ancestors (for tree display)."""
    if not category_ids:
        return set()
    Category = env["product.category"].sudo()
    result = set(category_ids)
    to_visit = list(category_ids)
    while to_visit:
        cid = to_visit.pop()
        cat = Category.browse(cid)
        if not cat.exists():
            continue
        parent = getattr(cat, "parent_id", None)
        if parent and parent.id and parent.id not in result:
            result.add(parent.id)
            to_visit.append(parent.id)
    return result


class CatalogCategoriesAPI(http.Controller):
    """MXM catalog categories endpoint."""

    @http.route(
        "/api/v1/mxm/categories",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def categories(self, warehouse_id=None, **kwargs):
        """GET /api/v1/mxm/categories – list categories; optional warehouse_id to limit by stock."""
        request_id = get_request_id()
        try:
            _logger.info(
                "mxm.categories called",
                extra={"request_id": request_id, "warehouse_id": warehouse_id},
            )
            user, err = _require_user(request_id)
            if err is not None:
                return err

            env = http.request.env
            Category = env["product.category"].sudo()

            if warehouse_id is not None and warehouse_id != "":
                # Resolve warehouse (same logic as products)
                warehouse = None
                try:
                    wh_id = int(warehouse_id)
                    Warehouse = env["stock.warehouse"].sudo()
                    warehouse = Warehouse.browse(wh_id)
                    if not warehouse.exists():
                        warehouse = None
                except (TypeError, ValueError):
                    pass
                if warehouse is None:
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
                    return fail(
                        message="Set your location first (aimag/sum) or provide a valid warehouse_id.",
                        code="WAREHOUSE_NOT_SET",
                        http_status=400,
                        request_id=request_id,
                    )
                warehouse = warehouse.sudo()
                product_ids = _product_ids_with_stock_in_warehouse(env, warehouse)
                if not product_ids:
                    # No products in stock -> return empty category list (or root categories with no children)
                    data = []
                    return ok(data=data, meta={"count": 0}, request_id=request_id)
                # Category IDs that have at least one product in this warehouse
                Product = env["product.product"].sudo()
                products = Product.browse(product_ids)
                category_ids_with_products = set()
                for p in products:
                    if p.categ_id:
                        category_ids_with_products.add(p.categ_id.id)
                # Include ancestors so tree makes sense
                all_category_ids = _category_ids_with_ancestors(env, category_ids_with_products)
                categories = Category.search([("id", "in", list(all_category_ids))], order="complete_name")
            else:
                # All product categories
                categories = Category.search([], order="complete_name")

            def _has_image(cat):
                return bool(
                    getattr(cat, "image_1920", None) or getattr(cat, "image_512", None)
                )

            def _has_icon(cat):
                # Use stored flag to avoid loading binary in list (ORM safety)
                if not getattr(cat, "x_icon_enabled", True):
                    return False
                return bool(getattr(cat, "x_icon_has_image", False))

            data = []
            for cat in categories:
                write_date_str = cat.write_date.isoformat() if cat.write_date else ""
                image_url = None
                if _has_image(cat):
                    image_url = "/api/v1/mxm/category-image/%s?size=256&v=%s" % (
                        cat.id,
                        write_date_str,
                    )
                icon_url = None
                icon_updated_at = None
                if _has_icon(cat):
                    icon_ver = (
                        cat.x_icon_updated_at.isoformat()
                        if getattr(cat, "x_icon_updated_at", None)
                        else write_date_str
                    )
                    icon_url = "/api/v1/mxm/category-icon/%s?size=128&v=%s" % (
                        cat.id,
                        icon_ver,
                    )
                    icon_updated_at = (
                        cat.x_icon_updated_at.isoformat()
                        if getattr(cat, "x_icon_updated_at", None)
                        else write_date_str
                    )
                data.append({
                    "id": cat.id,
                    "name": cat.name,
                    "parent_id": cat.parent_id.id if cat.parent_id else None,
                    "sequence": getattr(cat, "sequence", 0),
                    "image_url": image_url,
                    "icon_url": icon_url,
                    "icon_updated_at": icon_updated_at,
                })

            meta = {"count": len(data)}
            return ok(data=data, meta=meta, request_id=request_id)
        except Exception as e:
            _logger.exception(
                "mxm.categories error: %s",
                e,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="SERVER_ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/mxm/category-names",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def category_names(self, **kwargs):
        """GET /api/v1/mxm/category-names – list id, name, complete_name for Excel import matching (session required)."""
        request_id = get_request_id()
        try:
            user, err = _require_user(request_id)
            if err is not None:
                return err
            env = http.request.env
            Category = env["product.category"].sudo()
            categories = Category.search([], order="complete_name")
            data = [
                {
                    "id": c.id,
                    "name": c.name,
                    "complete_name": getattr(c, "complete_name", None) or c.name,
                }
                for c in categories
            ]
            meta = {"count": len(data)}
            return ok(data=data, meta=meta, request_id=request_id)
        except Exception as e:
            _logger.exception(
                "mxm.category_names error: %s",
                e,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="SERVER_ERROR",
                http_status=500,
                request_id=request_id,
            )
