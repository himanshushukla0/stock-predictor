"""
Re-export companies catalog/search module as symbols under sources package.
"""
from companies import (
    CATALOG,
    REGION_LABELS,
    ALIASES,
    search_catalog,
    search,
    catalog_grouped,
)

__all__ = [
    "CATALOG",
    "REGION_LABELS",
    "ALIASES",
    "search_catalog",
    "search",
    "catalog_grouped",
]
