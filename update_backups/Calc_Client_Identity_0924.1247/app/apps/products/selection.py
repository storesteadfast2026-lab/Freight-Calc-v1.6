"""Protect Product selection when SKU is reused by commercial customers."""

from apps.products.identity import normalize_customer
from apps.products.models import Product


def validate_product_selection(client, sku, customer_code='', product_id=None):
    if not sku:
        return
    products = Product.objects.filter(client=client, sku__iexact=sku, active=True)
    if product_id:
        if not products.filter(pk=product_id, customer_code=normalize_customer(customer_code)).exists():
            raise ValueError('The selected Product does not belong to this client, CUSTOMER and SKU.')
    elif products.values('customer_code').distinct().count() > 1:
        raise ValueError(f'{sku}: select a Product with its CUSTOMER from the search results.')
