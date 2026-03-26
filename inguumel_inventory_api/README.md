# Inguumel Inventory API

Odoo 19 module providing REST API endpoints for React Native mobile app.

## Installation

1. Copy module to Odoo addons directory:
```bash
sudo cp -r /root/inguumel_inventory_api /opt/odoo/custom_addons/
```

2. Update Odoo app list:
```bash
# Via Odoo UI: Apps > Update Apps List
# Or via command line:
odoo-bin -d InguumelStage -u base --stop-after-init
```

3. Install module:
```bash
# Via Odoo UI: Apps > Search "Inguumel Inventory API" > Install
# Or via command line:
odoo-bin -d InguumelStage -i inguumel_inventory_api
```

## API Endpoints

### GET /api/v1/products

Returns paginated list of active storable products.

**Query Parameters:**
- `page` (int, default: 1) - Page number
- `limit` (int, default: 20, max: 100) - Items per page

**Response:**
```json
{
  "success": true,
  "page": 1,
  "limit": 20,
  "total": 57,
  "products": [
    {
      "id": 1,
      "name": "Product Name",
      "price": 99.99,
      "qty_available": 150.0,
      "image_url": "http://72.62.247.95:8069/api/v1/product-image/1",
      "uom": "Units"
    }
  ]
}
```

### GET /api/v1/product-image/<product_id>

Returns product image binary.

**Response:**
- 200: Image binary with `Content-Type: image/png`
- 404: Product not found or has no image

## Testing with curl

### List products (first page)
```bash
curl -X GET "http://72.62.247.95:8069/api/v1/products?page=1&limit=20" \
  -H "Content-Type: application/json"
```

### List products (pagination example)
```bash
# Page 2 with 10 items per page
curl -X GET "http://72.62.247.95:8069/api/v1/products?page=2&limit=10" \
  -H "Content-Type: application/json"
```

### Get product image
```bash
# Replace 1 with actual product ID
curl -X GET "http://72.62.247.95:8069/api/v1/product-image/1" \
  --output product_image.png
```

### Pretty print JSON response
```bash
curl -X GET "http://72.62.247.95:8069/api/v1/products?page=1&limit=5" \
  -H "Content-Type: application/json" | python3 -m json.tool
```

## React Native Integration Notes

1. **Base URL**: `http://72.62.247.95:8069`

2. **Image Loading**: Use `image_url` from product response directly with React Native `Image` component:
```javascript
<Image 
  source={{ uri: product.image_url }} 
  style={{ width: 100, height: 100 }}
/>
```

3. **Pagination**: Use `page` and `limit` query params. Check `total` to determine if more pages exist.

4. **Error Handling**: 
   - Check `success: true` in response
   - Handle 404 for missing images
   - Handle network errors

5. **CORS**: Endpoints are configured with `cors='*'` for cross-origin requests.

6. **Caching**: Image endpoint includes `Cache-Control: public, max-age=3600` headers.

## Module Structure

```
inguumel_inventory_api/
├── __init__.py
├── __manifest__.py
├── controllers/
│   ├── __init__.py
│   └── main.py
├── security/
│   └── ir.model.access.csv
└── README.md
```
