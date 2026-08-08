"""Brand-aware client for the ctpa-oneapi connected-services backend.

Toyota, Lexus, and Subaru all run on the same gateway; the brand only changes
the ForgeRock tenant, a handful of request headers, and whether an account
bootstrap call is needed before vehicle discovery works. See brands.py.
"""
from .auth import OneAuth
from .brands import BRANDS, DEFAULT_BRAND, BrandConfig, get_brand
from .client import OneClient

__all__ = [
    "BRANDS",
    "DEFAULT_BRAND",
    "BrandConfig",
    "OneAuth",
    "OneClient",
    "get_brand",
]
