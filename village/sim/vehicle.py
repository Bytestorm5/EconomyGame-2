"""A vehicle instance: moves goods between parcels, takes time, burns fuel.

All numbers come from the owning VehicleDef's modifier blocks. A trip is a
round trip: drive empty to the source parcel, load, drive back. Cost and
fuel use the loaded leg's cargo (weight/space x distance); speed degrades
with load, so the return leg is slower.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Tuple

from ..content import PRODUCTS, VEHICLES
from ..objects import VehicleDef
from . import config

if TYPE_CHECKING:
    from .plot import Plot


def cargo_of(product_id: str, qty: int) -> Tuple[float, float]:
    p = PRODUCTS.get(product_id)
    return (p.weight * qty, p.space * qty)


class Vehicle:
    def __init__(self, def_id: str):
        self.def_id = def_id
        self.busy_until = 0      # tick when the current trip completes
        self.fuel_due = 0.0      # unpaid fuel, in demand points
        self.trips = 0

    @property
    def definition(self) -> VehicleDef:
        return VEHICLES.get(self.def_id)

    def idle(self, tick: int) -> bool:
        return tick >= self.busy_until

    @property
    def blocked(self) -> bool:
        """Too hungry/unfueled to start a normal trip."""
        return self.fuel_due >= config.FUEL_BLOCK_THRESHOLD

    def max_qty(self, product_id: str) -> int:
        """Units of the product that fit in one load."""
        p = PRODUCTS.get(product_id)
        c = self.definition.cargo
        by_weight = c.weight / p.weight if p.weight > 0 else float("inf")
        by_space = c.space / p.space if p.space > 0 else float("inf")
        return max(0, int(min(by_weight, by_space)))

    def leg_speed(self, weight: float, space: float) -> float:
        return max(1.0, self.definition.speed.evaluate(weight=weight,
                                                       space=space))

    def trip_ticks(self, dist: float, product_id: str, qty: int) -> int:
        """Round trip: out empty, back loaded (slower)."""
        w, s = cargo_of(product_id, qty)
        out = dist / self.leg_speed(0.0, 0.0)
        back = dist / self.leg_speed(w, s)
        return max(1, math.ceil(out + back))

    def trip_cost(self, dist: float, product_id: str, qty: int) -> float:
        w, s = cargo_of(product_id, qty)
        ticks = self.trip_ticks(dist, product_id, qty)
        return self.definition.cost.evaluate(
            ticks=ticks, tiles=2 * dist, weight=w * dist, space=s * dist)

    def trip_fuel(self, dist: float, product_id: str, qty: int) -> float:
        w, s = cargo_of(product_id, qty)
        ticks = self.trip_ticks(dist, product_id, qty)
        return self.definition.fuel.amount.evaluate(
            ticks=ticks, tiles=2 * dist, weight=w * dist, space=s * dist)

    def status(self, tick: int) -> str:
        if not self.idle(tick):
            return f"en route, back in {self.busy_until - tick}t"
        if self.blocked:
            return "unfed (refusing trips)"
        return "idle"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Vehicle {self.def_id} fuel_due={self.fuel_due:.1f}>"
