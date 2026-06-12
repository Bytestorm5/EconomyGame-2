"""Pre-set parcels of land: machine slots, a capacity-limited local
inventory, and ownership."""

from __future__ import annotations

import math
from collections import Counter
from typing import List, Optional, Tuple

from ..content import PRODUCTS
from . import config
from .machine import Machine


class Plot:
    def __init__(self, plot_id: int, rect: Tuple[int, int, int, int],
                 slots: int = config.PLOT_SLOTS):
        self.id = plot_id
        self.rect = rect  # (x, y, w, h) in map tiles
        self.owner_id: Optional[int] = None
        self.slots: List[Optional[Machine]] = [None] * slots
        # Goods physically located at this parcel. Moving goods between
        # parcels -- even your own -- takes a vehicle trip.
        self.inventory: Counter = Counter()
        # Weight/space reserved for goods currently on their way here.
        self.reserved_weight = 0.0
        self.reserved_space = 0.0
        # Set to a price to offer this parcel on the land market.
        self.for_sale_price: Optional[int] = None
        self.acquired_day = 0  # sim day the current owner took possession

    @property
    def center(self) -> Tuple[float, float]:
        x, y, w, h = self.rect
        return (x + w / 2, y + h / 2)

    def distance_to(self, other: "Plot") -> float:
        ax, ay = self.center
        bx, by = other.center
        return abs(ax - bx) + abs(ay - by)  # manhattan, in tiles

    def free_slot(self) -> Optional[int]:
        for i, m in enumerate(self.slots):
            if m is None:
                return i
        return None

    def machines(self) -> List[Machine]:
        return [m for m in self.slots if m is not None]

    def resells(self) -> bool:
        """True if a reseller building (store/warehouse) is on this parcel."""
        return any(m.definition.resells for m in self.machines())

    # --- storage ---------------------------------------------------------------
    def capacity(self) -> Tuple[float, float]:
        """(weight, space) this parcel can store: a bare-parcel base plus
        whatever its buildings (warehouses, stores) add."""
        w = config.BASE_PARCEL_STORAGE_WEIGHT
        s = config.BASE_PARCEL_STORAGE_SPACE
        for m in self.machines():
            if m.definition.storage is not None:
                w += m.definition.storage.weight
                s += m.definition.storage.space
        return (w, s)

    def used(self) -> Tuple[float, float]:
        w = s = 0.0
        for pid, qty in self.inventory.items():
            if qty > 0:
                p = PRODUCTS.get(pid)
                w += p.weight * qty
                s += p.space * qty
        return (w, s)

    def free_capacity(self) -> Tuple[float, float]:
        cw, cs = self.capacity()
        uw, us = self.used()
        return (cw - uw - self.reserved_weight, cs - us - self.reserved_space)

    def fits(self, product_id: str, qty: int) -> bool:
        p = PRODUCTS.get(product_id)
        fw, fs = self.free_capacity()
        return p.weight * qty <= fw + 1e-9 and p.space * qty <= fs + 1e-9

    def max_fit(self, product_id: str) -> int:
        """Most units of the product that still fit (after reservations)."""
        p = PRODUCTS.get(product_id)
        fw, fs = self.free_capacity()
        by_w = fw / p.weight if p.weight > 0 else float("inf")
        by_s = fs / p.space if p.space > 0 else float("inf")
        return max(0, math.floor(min(by_w, by_s) + 1e-9))

    def reserve(self, product_id: str, qty: int) -> None:
        p = PRODUCTS.get(product_id)
        self.reserved_weight += p.weight * qty
        self.reserved_space += p.space * qty

    def release(self, product_id: str, qty: int) -> None:
        p = PRODUCTS.get(product_id)
        self.reserved_weight = max(0.0, self.reserved_weight - p.weight * qty)
        self.reserved_space = max(0.0, self.reserved_space - p.space * qty)
