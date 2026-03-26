from odoo import http
from odoo.http import request
import werkzeug.exceptions
import base64
import json


class InventoryAPI(http.Controller):
    """REST API controller for inventory products"""

    @http.route('/api/v1/products', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_products(self, page=1, limit=20, **kwargs):
        """
        Get paginated list of active storable products
        
        Query params:
            page: Page number (default: 1)
            limit: Items per page (default: 20)
        
        Returns:
            JSON response with paginated product data
        """
        try:
            page = int(page)
            limit = int(limit)
        except (ValueError, TypeError):
            page = 1
            limit = 20
        
        # Ensure reasonable limits
        limit = min(max(1, limit), 100)  # Between 1 and 100
        page = max(1, page)
        
        # Get base URL for image endpoint
        base_url = request.httprequest.url_root.rstrip('/')
        
        # Query active storable products
        products = request.env['product.product'].sudo().search([
            ('active', '=', True),
            ('type', '=', 'product'),
        ], order='id')
        
        total = len(products)
        
        # Pagination
        offset = (page - 1) * limit
        paginated_products = products[offset:offset + limit]
        
        # Build response data
        products_data = []
        for product in paginated_products:
            # Build image URL if product has image
            image_url = None
            if product.image_1920:
                image_url = f"{base_url}/api/v1/product-image/{product.id}"
            
            products_data.append({
                'id': product.id,
                'name': product.name,
                'price': product.list_price,
                'qty_available': product.qty_available,
                'image_url': image_url,
                'uom': product.uom_id.name if product.uom_id else '',
            })
        
        response_data = {
            'success': True,
            'page': page,
            'limit': limit,
            'total': total,
            'products': products_data,
        }
        
        return request.make_response(
            data=json.dumps(response_data),
            headers=[('Content-Type', 'application/json')]
        )

    @http.route('/api/v1/product-image/<int:product_id>', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_product_image(self, product_id, **kwargs):
        """
        Get product image binary
        
        Args:
            product_id: Product ID
        
        Returns:
            Image binary with appropriate Content-Type, or 404 if no image
        """
        product = request.env['product.product'].sudo().browse(product_id)
        
        if not product.exists() or not product.active:
            return werkzeug.exceptions.NotFound()
        
        if not product.image_1920:
            return werkzeug.exceptions.NotFound()
        
        # Decode base64 image data
        try:
            image_data = base64.b64decode(product.image_1920)
        except Exception:
            return werkzeug.exceptions.NotFound()
        
        content_type = 'image/png'  # Odoo stores images as PNG
        
        # Set cache-friendly headers
        headers = [
            ('Content-Type', content_type),
            ('Cache-Control', 'public, max-age=3600'),
        ]
        
        return request.make_response(
            data=image_data,
            headers=headers
        )
