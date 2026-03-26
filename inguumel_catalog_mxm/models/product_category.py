# -*- coding: utf-8 -*-
"""
Extend product.category with optional icon (PNG/SVG) for mobile sidebar.
Icon stored as attachment; API exposes icon_url and category-icon proxy.
"""
import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MAX_ICON_SIZE_BYTES = 300 * 1024  # 300 KB
ALLOWED_ICON_MIMES = ("image/png", "image/svg+xml")


class ProductCategory(models.Model):
    _inherit = "product.category"

    x_icon_image = fields.Binary(
        string="Category Icon",
        attachment=True,
        help="PNG or SVG icon for mobile app sidebar (max 300 KB).",
    )
    x_icon_mime = fields.Char(
        string="Icon MIME",
        help="Content-Type of the icon (image/png or image/svg+xml).",
    )
    x_icon_updated_at = fields.Datetime(
        string="Icon Updated At",
        related="write_date",
        store=True,
        readonly=True,
    )
    x_icon_enabled = fields.Boolean(
        string="Icon Enabled",
        default=True,
        help="If unchecked, icon is not exposed via API.",
    )
    x_icon_has_image = fields.Boolean(
        string="Has Icon",
        default=False,
        store=True,
        help="Technical: True when x_icon_image is set (avoids loading binary in list API).",
    )

    @staticmethod
    def _mime_from_icon_bytes(data):
        """Detect MIME from magic bytes. Returns image/png, image/svg+xml, or None."""
        if not data or len(data) < 4:
            return None
        if data[:4] == b"\x89PNG":
            return "image/png"
        # SVG: <?xml or <svg
        start = data.lstrip()[:100]
        if start.startswith(b"<"):
            if b"svg" in start.lower() or b"<?xml" in start.lower():
                return "image/svg+xml"
        return None

    def _check_icon_content(self, data_b64, mime):
        """Validate icon size and type. Raise UserError on failure."""
        if not data_b64:
            return
        try:
            data = base64.b64decode(data_b64, validate=True)
        except Exception as e:
            raise UserError(
                _("Invalid icon data: %s") % (e,)
            ) from e
        if len(data) > MAX_ICON_SIZE_BYTES:
            raise UserError(
                _("Icon size must not exceed 300 KB (current: %s bytes).")
                % len(data)
            )
        resolved_mime = (mime or "").strip().lower() or self._mime_from_icon_bytes(data)
        if resolved_mime and resolved_mime not in ALLOWED_ICON_MIMES:
            raise UserError(
                _("Icon must be PNG or SVG (image/png or image/svg+xml). Got: %s")
                % (resolved_mime or "unknown")
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "x_icon_image" in vals or "x_icon_mime" in vals:
                self._check_icon_content(
                    vals.get("x_icon_image"),
                    vals.get("x_icon_mime"),
                )
                # Auto-set mime from content if missing
                if vals.get("x_icon_image") and not (vals.get("x_icon_mime") or "").strip():
                    data = base64.b64decode(vals["x_icon_image"], validate=True)
                    inferred = self._mime_from_icon_bytes(data)
                    if inferred:
                        vals["x_icon_mime"] = inferred
                vals["x_icon_has_image"] = bool(vals.get("x_icon_image"))
        return super().create(vals_list)

    def write(self, vals):
        if "x_icon_image" in vals or "x_icon_mime" in vals:
            self._check_icon_content(
                vals.get("x_icon_image"),
                vals.get("x_icon_mime"),
            )
            icon_data = vals.get("x_icon_image")
            if icon_data and not (vals.get("x_icon_mime") or "").strip():
                data = base64.b64decode(icon_data, validate=True)
                inferred = self._mime_from_icon_bytes(data)
                if inferred:
                    vals["x_icon_mime"] = inferred
            if "x_icon_image" in vals:
                vals["x_icon_has_image"] = bool(vals.get("x_icon_image"))
        return super().write(vals)
