"""Pre-set plots of land that machines are placed on."""

from __future__ import annotations

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

    @property
    def center(self) -> Tuple[float, float]:
        x, y, w, h = self.rect
        return (x + w / 2, y + h / 2)

    def free_slot(self) -> Optional[int]:
        for i, m in enumerate(self.slots):
            if m is None:
                return i
        return None

    def machines(self) -> List[Machine]:
        return [m for m in self.slots if m is not None]
