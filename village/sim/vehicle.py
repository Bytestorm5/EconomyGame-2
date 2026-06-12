"""A vehicle instance: moves goods between parcels, takes time, burns fuel.

Vehicles are *parked* at a specific parcel. A trip has two legs: drive
empty from wherever the vehicle is parked to the source parcel, load, then
drive loaded to the destination -- where it stays parked. Cost and fuel
charge the empty leg by distance and the loaded leg by distance and cargo;
speed degrades with load, so the loaded leg is slower.

All numbers come from the owning VehicleDef's modifier blocks (dollars in
JSON; the sim converts to integer cents at the quote boundary).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Optional, Tuple

from ..content import PRODUCTS, VEHICLES
from ..objects import VehicleDef
from . import config

if TYPE_CHECKING:
    from .plot import Plot


def cargo_of(product_id: str, qty: int) -> Tuple[float, float]:
    p = PRODUCTS.get(product_id)
    return (p.weight * qty, p.space * qty)


class Vehicle:
    def __init__(self, def_id: str, plot: Optional["Plot"] = None):
        self.def_id = def_id
        self.plot = plot         # where it's parked (or will be, post-trip)
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

    @staticmethod
    def manifest_cargo(items: dict) -> Tuple[float, float]:
        w = sum(PRODUCTS.get(pid).weight * q for pid, q in items.items())
        s = sum(PRODUCTS.get(pid).space * q for pid, q in items.items())
        return (w, s)

    def fits(self, items: dict) -> bool:
        w, s = self.manifest_cargo(items)
        c = self.definition.cargo
        return w <= c.weight + 1e-9 and s <= c.space + 1e-9

    def trip_ticks(self, d_empty: float, d_loaded: float,
                   product_id=None, qty: int = 0, *,
                   cargo: Tuple[float, float] = None) -> int:
        """Empty positioning leg + loaded delivery leg. Cargo is either a
        (weight, space) manifest total or a single product+qty."""
        w, s = cargo if cargo is not None else cargo_of(product_id, qty)
        out = d_empty / self.leg_speed(0.0, 0.0)
        back = d_loaded / self.leg_speed(w, s)
        return max(1, math.ceil(out + back))

    def trip_cost(self, d_empty: float, d_loaded: float,
                  product_id=None, qty: int = 0, *,
                  cargo: Tuple[float, float] = None) -> float:
        """Dollars (content units); callers convert to cents."""
        w, s = cargo if cargo is not None else cargo_of(product_id, qty)
        ticks = self.trip_ticks(d_empty, d_loaded, cargo=(w, s))
        return self.definition.cost.evaluate(
            ticks=ticks, tiles=d_empty + d_loaded,
            weight=w * d_loaded, space=s * d_loaded)

    def trip_fuel(self, d_empty: float, d_loaded: float,
                  product_id=None, qty: int = 0, *,
                  cargo: Tuple[float, float] = None) -> float:
        w, s = cargo if cargo is not None else cargo_of(product_id, qty)
        ticks = self.trip_ticks(d_empty, d_loaded, cargo=(w, s))
        return self.definition.fuel.amount.evaluate(
            ticks=ticks, tiles=d_empty + d_loaded,
            weight=w * d_loaded, space=s * d_loaded)

    def status(self, tick: int) -> str:
        if not self.idle(tick):
            return f"en route, back in {self.busy_until - tick}t"
        if self.blocked:
            return "unfed (refusing trips)"
        return "idle"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Vehicle {self.def_id} fuel_due={self.fuel_due:.1f}>"
