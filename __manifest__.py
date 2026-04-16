{
    'name': 'INIES Connector',
    'version': '19.0.1.0.1',
    'category': 'Inventory',
    'summary': 'Recherche et import de produits depuis la base INIES directement dans Odoo',
    'author': 'ibatix',
    'depends': ['product', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
        'views/inies_search_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
