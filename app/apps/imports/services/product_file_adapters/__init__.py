"""Format adapters for Product master source files.

The Product import workflow consumes only :class:`ProductFileReadResult` and is
therefore independent from the physical source format.  Registering a new
reader here is the only integration point required for a future format.
"""

from .adapter import (
    PRODUCT_SOURCE_EXTENSIONS,
    ProductFileReadResult,
    read_product_file,
)

__all__ = (
    'PRODUCT_SOURCE_EXTENSIONS',
    'ProductFileReadResult',
    'read_product_file',
)
