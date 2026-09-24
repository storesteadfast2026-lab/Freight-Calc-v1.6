"""A Product belongs to a calculator client and a Translogic CUSTOMER."""

def normalize_customer(value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value or '').strip().upper()


def product_identity(customer, sku):
    """Legacy sources retain SKU keys; new sources use unambiguous CUSTOMER keys.

    CUSTOMER codes must be restricted at the import boundary. SKU values may
    contain the separator; they are never split or interpreted as CUSTOMER.
    """
    customer = normalize_customer(customer)
    return f'{customer}::{sku}' if customer else sku


def valid_customer(value):
    code = normalize_customer(value)
    # The separator cannot appear in CUSTOMER; other printable source codes
    # (including spaces) are preserved instead of guessing their syntax.
    return bool(code) and len(code) <= 100 and ':' not in code and all(ord(c) >= 32 for c in code)
