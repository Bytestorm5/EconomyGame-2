"""Product definitions.

A product is anything that can sit in an inventory and be traded.
``food_value > 0`` means a hungry person can eat one unit of it to reduce
hunger by ``food_value * HUNGER_PER_FOOD_VALUE`` (see sim.config).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from ..registry import REGISTRY, ContentDef


@dataclass(frozen=True)
class ProductDef(ContentDef):
    base_price: int
    color: Tuple[int, int, int]  # placeholder asset: solid color swatch
    food_value: int = 0


PRODUCTS = REGISTRY.category("product", ProductDef)


def register_products() -> None:
    PRODUCTS.register(ProductDef(
        id="grain", name="Grain", base_price=2, color=(218, 185, 90)))
    PRODUCTS.register(ProductDef(
        id="wood", name="Wood", base_price=2, color=(125, 88, 52)))
    PRODUCTS.register(ProductDef(
        id="flour", name="Flour", base_price=5, color=(238, 232, 215)))
    # By-product of milling; cheap, low-grade food.
    PRODUCTS.register(ProductDef(
        id="bran", name="Bran", base_price=2, color=(186, 150, 97), food_value=1))
    PRODUCTS.register(ProductDef(
        id="bread", name="Bread", base_price=10, color=(205, 133, 63), food_value=3))
