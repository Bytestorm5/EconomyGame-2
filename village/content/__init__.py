"""Game content. Call :func:`load_all` once at startup."""

from __future__ import annotations

from ..registry import REGISTRY
from .machines import MACHINES, register_machines
from .products import PRODUCTS, register_products

_loaded = False


def load_all(force: bool = False) -> None:
    global _loaded
    if _loaded and not force:
        return
    REGISTRY.clear()
    register_products()
    register_machines()
    _loaded = True


__all__ = ["load_all", "PRODUCTS", "MACHINES"]
