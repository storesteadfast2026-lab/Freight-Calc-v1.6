"""Validate a selected Product against the resolved Client on the server."""
from apps.products.models import Product


def validate_product_selection(client, sku, customer_code='', product_id=None):
    # customer_code is accepted only for existing quotation payload compatibility.
    # It does not select a second Product namespace.
    products = Product.objects.filter(client=client, sku=str(sku or '').strip(), active=True)
    if product_id is not None:
        if not products.filter(pk=product_id).exists():
            raise ValueError('The selected Product does not belong to the authorised Client.')
    elif not products.exists():
        raise ValueError('The selected Product does not belong to the authorised Client.')
    return products.first()
