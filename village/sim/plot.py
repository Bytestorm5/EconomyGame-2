"""Pre-set parcels of land: machine slots, a local inventory, ownership."""

from __future__ import annotations

from collections import Counter
from typing import List, Optional, Tuple

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
        # parcels -- even your own -- costs shipping per tile of distance.
        self.inventory: Counter = Counter()
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
