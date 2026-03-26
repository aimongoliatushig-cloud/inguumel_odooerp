{
    'name': 'Inguumel Inventory API',
    'version': '19.0.1.0.0',
    'category': 'API',
    'summary': 'REST API for mobile app to access inventory products',
    'description': """
        Provides JSON API endpoints for React Native mobile app:
        - GET /api/v1/products (paginated product list)
        - GET /api/v1/product-image/<product_id> (product image binary)
    """,
    'author': 'Inguumel',
    'depends': ['base', 'product', 'stock'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
