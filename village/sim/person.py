"""People: money, parcels, demands, knowledge, selling, and bookkeeping."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Deque, Dict, List, Optional, Set, Tuple

from ..content import MACHINES, PRODUCTS
from . import config

if TYPE_CHECKING:
    from .machine import Machine
    from .plot import Plot


@lru_cache(maxsize=None)
def min_sale_price(product_id: str) -> int:
    """Floor price so producers never sell below (base-price) input cost.

    Joint outputs share input cost evenly by quantity -- crude, but it keeps
    every step of the chain profitable at the floor.
    """
    floor = config.PRICE_MIN
    for mdef in MACHINES:
        if product_id not in mdef.outputs:
            continue
        input_cost = sum(PRODUCTS.get(pid).base_price * qty
                         for pid, qty in mdef.inputs.items())
        total_out = sum(mdef.outputs.values())
        if input_cost > 0 and total_out > 0:
            floor = max(floor, math.ceil(input_cost / total_out) + 1)
    return floor


@dataclass
class ProductDayStats:
    """One person's activity on one product over one sim day."""
    produced: int = 0    # made by own machines
    consumed: int = 0    # eaten by own machines as inputs
    sold: int = 0        # units sold to others
    revenue: int = 0     # coin earned selling
    spent: int = 0       # coin spent buying this product (incl. shipping)
    stock_end: int = 0   # inventory at end of day (all parcels)

    @property
    def profit(self) -> int:
        return self.revenue - self.spent


class Person:
    def __init__(self, pid: int, name: str, money: int, is_player: bool = False):
        self.id = pid
        self.name = name
        self.money = money
        self.is_player = is_player

        # Parcels owned, in acquisition order; plots[0] is "home", where
        # this person's demands are fulfilled from. Never sold.
        self.plots: List["Plot"] = []

        # Demand state: points per demand id, plus loyalty memory of the
        # last (seller id, product id) that fulfilled each demand.
        self.demands: Dict[str, float] = {}
        self.demand_memory: Dict[str, Tuple[int, str]] = {}
        self.unfulfilled: Dict[str, int] = {}  # need-urgency ticks unmet

        # Knowledge graph: ids of people this person knows.
        self.knowledge: Set[int] = set()

        # Sale prices per product id (one price across all parcels). Only
        # products this person produces (machine outputs) are for sale.
        self.prices: Dict[str, int] = {}

        # Per-product bookkeeping: today's running counters and a rolling
        # window of finished days (most recent last).
        self.stats_today: Dict[str, ProductDayStats] = {}
        self.stats_history: Dict[str, Deque[ProductDayStats]] = {}

        self.machines: List["Machine"] = []  # all machines on all parcels

    # --- parcels & inventory -------------------------------------------------
    @property
    def home(self) -> "Plot":
        assert self.plots, f"{self.name} owns no parcel"
        return self.plots[0]

    def stock(self, product_id: str) -> int:
        """Total stock across all owned parcels."""
        return sum(p.inventory.get(product_id, 0) for p in self.plots)

    def add_items(self, product_id: str, qty: int,
                  plot: Optional["Plot"] = None) -> None:
        (plot or self.home).inventory[product_id] += qty

    def remove_items(self, product_id: str, qty: int,
                     plot: Optional["Plot"] = None) -> None:
        store = (plot or self.home).inventory
        if store.get(product_id, 0) < qty:
            raise ValueError(f"{self.name} lacks {qty} {product_id}")
        store[product_id] -= qty

    # --- bookkeeping ---------------------------------------------------------
    def stat(self, product_id: str) -> ProductDayStats:
        if product_id not in self.stats_today:
            self.stats_today[product_id] = ProductDayStats()
        return self.stats_today[product_id]

    def yesterday(self, product_id: str) -> Optional[ProductDayStats]:
        hist = self.stats_history.get(product_id)
        return hist[-1] if hist else None

    def sellout_days(self, product_id: str) -> int:
        """Days in the rolling window where the product sold and ended empty."""
        hist = self.stats_history.get(product_id, ())
        return sum(1 for d in hist if d.sold > 0 and d.stock_end == 0)

    def end_of_day(self) -> None:
        tracked = set(self.stats_today) | self.produced_products()
        for pid in tracked:
            day = self.stats_today.get(pid, ProductDayStats())
            day.stock_end = self.stock(pid)
            hist = self.stats_history.setdefault(
                pid, deque(maxlen=config.STATS_WINDOW_DAYS))
            hist.append(day)
        self.stats_today = {}
        for machine in self.machines:
            machine.end_of_day()

    # --- selling -----------------------------------------------------------
    def produced_products(self) -> Set[str]:
        out: Set[str] = set()
        for m in self.machines:
            out.update(m.definition.outputs.keys())
        return out

    def sells(self, product_id: str) -> bool:
        """True if this person offers product_id for sale right now."""
        return (
            product_id in self.produced_products()
            and self.stock(product_id) > 0
        )

    def price_of(self, product_id: str) -> int:
        if product_id not in self.prices:
            self.prices[product_id] = PRODUCTS.get(product_id).base_price
        return self.prices[product_id]

    def adjust_prices_daily(self) -> None:
        """Supply-demand price discovery from what this seller observed today:
        sold out -> raise; didn't sell at all -> lower; selling steadily with
        stock left -> hold. The player sets prices manually."""
        if self.is_player:
            return
        for pid in self.produced_products():
            price = self.price_of(pid)
            sold = self.stat(pid).sold
            stock = self.stock(pid)
            if sold > 0 and stock == 0:
                price = max(int(price * config.PRICE_UP_FACTOR), price + 1)
            elif sold == 0 and stock > 0:
                price = max(min_sale_price(pid),
                            int(price * config.PRICE_DOWN_FACTOR))
            self.prices[pid] = price

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Person {self.id} {self.name} ${self.money}>"
