# -*- coding: utf-8 -*-
"""
GET /api/v1/mxm/product-image/<product_id> – product image proxy (never /web/image).
GET /api/v1/mxm/category-image/<category_id> – category main image proxy (404 if no image).
GET /api/v1/mxm/category-icon/<category_id> – category icon proxy (PNG/SVG, 404 if no icon).

MIME type is detected from raw bytes so Content-Type matches actual format.
Category icon uses x_icon_image + x_icon_mime; same auth as categories list.
"""
import base64
import hashlib
import logging

from werkzeug.wrappers import Response

from odoo import http

from odoo.addons.inguumel_mobile_api.controllers.base import (
    get_request_id,
    fail,
)

_logger = logging.getLogger(__name__)

ALLOWED_SIZES = (256, 512, 1024, 1920)


def _mime_from_image_bytes(data):
    """Detect Content-Type from image magic bytes.
    - RIFF....WEBP => image/webp
    - 89 50 4E 47 => image/png
    - FF D8 FF => image/jpeg
    - else => application/octet-stream
    """
    if not data or len(data) < 12:
        return "application/octet-stream"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    return "application/octet-stream"
SIZE_FIELDS = {
    256: "image_256",
    512: "image_512",
    1024: "image_1024",
    1920: "image_1920",
}
CATEGORY_SIZE_FIELDS = {
    256: "image_256",
    512: "image_512",
    1024: "image_1024",
    1920: "image_1920",
}
DEFAULT_SIZE = 1024
DEFAULT_CATEGORY_SIZE = 256
ICON_ALLOWED_SIZES = (128, 256)


def _require_user(request_id):
    """Return 401 if public user (same auth as categories list)."""
    user = http.request.env.user
    if not user or user._is_public():
        return None, fail(
            message="Unauthorized",
            code="UNAUTHORIZED",
            http_status=401,
            request_id=request_id,
        )
    return user, None


class CatalogImagesAPI(http.Controller):
    """MXM catalog product image proxy."""

    @http.route(
        "/api/v1/mxm/product-image/<int:product_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def product_image(self, product_id, size=None, v=None, auth=None, **kwargs):
        """GET /api/v1/mxm/product-image/<product_id> – return image bytes or 404 JSON.
        Optional auth: if query param auth=1, require Bearer token; else public (backward compatible).
        """
        request_id = get_request_id()
        try:
            if auth == "1" or auth == 1:
                user, err = _require_user(request_id)
                if err is not None:
                    return err
            _logger.info(
                "mxm.product_image called",
                extra={"request_id": request_id, "product_id": product_id},
            )
            try:
                size = int(size) if size is not None else DEFAULT_SIZE
            except (TypeError, ValueError):
                size = DEFAULT_SIZE
            if size not in ALLOWED_SIZES:
                size = DEFAULT_SIZE

            field_name = SIZE_FIELDS[size]
            product = (
                http.request.env["product.product"]
                .sudo()
                .browse(product_id)
            )
            if not product.exists():
                return fail(
                    message="IMAGE_NOT_FOUND",
                    code="IMAGE_NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            image_b64 = getattr(product, field_name, None)
            if not image_b64:
                return fail(
                    message="IMAGE_NOT_FOUND",
                    code="IMAGE_NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            image_bytes = base64.b64decode(image_b64)
            content_type = _mime_from_image_bytes(image_bytes)
            return Response(
                image_bytes,
                status=200,
                mimetype=content_type,
                headers={
                    "Content-Type": content_type,
                    "Cache-Control": "public, max-age=86400",
                },
            )
        except Exception as e:
            _logger.exception(
                "mxm.product_image error: %s request_id=%s",
                e,
                request_id,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="ERROR",
                http_status=500,
                request_id=request_id,
            )

    @http.route(
        "/api/v1/mxm/category-image/<int:category_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def category_image(self, category_id, size=None, v=None, **kwargs):
        """GET /api/v1/mxm/category-image/<category_id> – return image bytes or 404 JSON if no image."""
        request_id = get_request_id()
        try:
            _logger.info(
                "mxm.category_image called",
                extra={"request_id": request_id, "category_id": category_id},
            )
            try:
                size = int(size) if size is not None else DEFAULT_CATEGORY_SIZE
            except (TypeError, ValueError):
                size = DEFAULT_CATEGORY_SIZE
            if size not in ALLOWED_SIZES:
                size = DEFAULT_CATEGORY_SIZE

            field_name = CATEGORY_SIZE_FIELDS.get(size, "image_1920")
            category = (
                http.request.env["product.category"]
                .sudo()
                .browse(category_id)
            )
            if not category.exists():
                return fail(
                    message="IMAGE_NOT_FOUND",
                    code="IMAGE_NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            image_b64 = getattr(category, field_name, None)
            if not image_b64:
                image_b64 = getattr(category, "image_1920", None)
            if not image_b64:
                return fail(
                    message="IMAGE_NOT_FOUND",
                    code="IMAGE_NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            image_bytes = base64.b64decode(image_b64)
            content_type = _mime_from_image_bytes(image_bytes)
            return Response(
                image_bytes,
                status=200,
                mimetype=content_type,
                headers={
                    "Content-Type": content_type,
                    "Cache-Control": "public, max-age=86400",
                },
            )
        except Exception as e:
            _logger.exception(
                "mxm.category_image error: %s",
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
        "/api/v1/mxm/category-icon/<int:category_id>",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def category_icon(self, category_id, size=None, v=None, **kwargs):
        """GET /api/v1/mxm/category-icon/<category_id> – return icon bytes (PNG/SVG) or 404.
        Same auth as categories list. Only serves x_icon_image for this category (no arbitrary attachments).
        Cache-Control + ETag/Last-Modified for cache-busting.
        """
        request_id = get_request_id()
        try:
            _logger.info(
                "mxm.category_icon called",
                extra={"request_id": request_id, "category_id": category_id},
            )
            user, err = _require_user(request_id)
            if err is not None:
                return err

            category = (
                http.request.env["product.category"]
                .sudo()
                .browse(category_id)
            )
            if not category.exists():
                return fail(
                    message="ICON_NOT_FOUND",
                    code="ICON_NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            if not getattr(category, "x_icon_enabled", True):
                return fail(
                    message="ICON_NOT_FOUND",
                    code="ICON_NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            icon_b64 = getattr(category, "x_icon_image", None)
            if not icon_b64:
                return fail(
                    message="ICON_NOT_FOUND",
                    code="ICON_NOT_FOUND",
                    http_status=404,
                    request_id=request_id,
                )
            image_bytes = base64.b64decode(icon_b64)
            content_type = (
                (getattr(category, "x_icon_mime", None) or "").strip()
                or _mime_from_image_bytes(image_bytes)
            )
            if not content_type or content_type == "application/octet-stream":
                # SVG detection
                if image_bytes.lstrip()[:100].startswith(b"<"):
                    content_type = "image/svg+xml"
                else:
                    content_type = _mime_from_image_bytes(image_bytes)
            # ETag from write_date / version for cache validation
            write_date = getattr(category, "write_date", None)
            etag = None
            last_modified = None
            if write_date:
                etag = hashlib.md5(
                    ("%s-%s" % (category_id, write_date.isoformat())).encode()
                ).hexdigest()
                last_modified = write_date.strftime("%a, %d %b %Y %H:%M:%S GMT")
            headers = {
                "Content-Type": content_type,
                "Cache-Control": "public, max-age=86400",
            }
            if etag:
                headers["ETag"] = '"%s"' % etag
            if last_modified:
                headers["Last-Modified"] = last_modified
            return Response(
                image_bytes,
                status=200,
                mimetype=content_type,
                headers=headers,
            )
        except Exception as e:
            _logger.exception(
                "mxm.category_icon error: %s",
                e,
                extra={"request_id": request_id},
            )
            return fail(
                message="Internal error",
                code="SERVER_ERROR",
                http_status=500,
                request_id=request_id,
            )
