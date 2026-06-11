"""People: money, parcels, demands, knowledge, selling, and bookkeeping."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Deque, Dict, List, Optional, Set, Tuple

from ..content import MACHINES, PRODUCTS
from . import config
from .money import cents

if TYPE_CHECKING:
    from .machine import Machine
    from .plot import Plot
    from .vehicle import Vehicle


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
        input_cost = sum(cents(PRODUCTS.get(pid).base_price) * qty
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
        # Consecutive days of going meaningfully hungry; drives emigration.
        self.hungry_days = 0
        self._unfulfilled_seen = 0

        # Demand state: points per demand id, plus loyalty memory of the
        # last (seller id, product id) that fulfilled each demand.
        self.demands: Dict[str, float] = {}
        self.demand_memory: Dict[str, Tuple[int, str]] = {}
        self.unfulfilled: Dict[str, int] = {}  # need-urgency ticks unmet

        # Knowledge graph: ids of people this person knows. Edges to sellers
        # fade over time unless refreshed by purchases (see world tick).
        self.knowledge: Set[int] = set()
        self.last_bought: Dict[int, int] = {}   # seller id -> tick of last buy
        # Advertising: how often each seller's ads have hit this person
        # (past the threshold they intentionally forget the seller), and
        # this person's own campaign cooldowns (ad def id -> ready day).
        self.ad_fatigue: Dict[int, int] = {}
        self.ad_cooldowns: Dict[str, int] = {}
        # NPC ad effectiveness memory: (day, product) of the last campaign,
        # and until when they've given up on advertising entirely.
        self.ad_watch: Optional[Tuple[int, str]] = None
        self.ad_discouraged_until = 0

        # Sale prices per product id (one price across all parcels). Only
        # products this person produces (machine outputs) are for sale.
        self.prices: Dict[str, int] = {}

        # Per-product bookkeeping: today's running counters and a rolling
        # window of finished days (most recent last).
        self.stats_today: Dict[str, ProductDayStats] = {}
        self.stats_history: Dict[str, Deque[ProductDayStats]] = {}

        self.machines: List["Machine"] = []  # all machines on all parcels

        # Logistics: owned vehicles, goods en route keyed (dest plot id,
        # product id), and how often trips were capped by vehicle capacity
        # (the signal that a bigger vehicle would pay off).
        self.vehicles: List["Vehicle"] = []
        self.inbound: Dict[Tuple[int, str], int] = {}
        self.capped_trips = 0

    # --- parcels & inventory -------------------------------------------------
    @property
    def home(self) -> "Plot":
        assert self.plots, f"{self.name} owns no parcel"
        return self.plots[0]

    def stock(self, product_id: str) -> int:
        """Total stock across all owned parcels."""
        return sum(p.inventory.get(product_id, 0) for p in self.plots)

    def inbound_to(self, plot: "Plot", product_id: str) -> int:
        return self.inbound.get((plot.id, product_id), 0)

    def inbound_total(self, product_id: str) -> int:
        return sum(qty for (_, pid), qty in self.inbound.items()
                   if pid == product_id)

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
        tracked = set(self.stats_today) | self.sellable_products()
        for pid in tracked:
            day = self.stats_today.get(pid, ProductDayStats())
            day.stock_end = self.stock(pid)
            hist = self.stats_history.setdefault(
                pid, deque(maxlen=config.STATS_WINDOW_DAYS))
            hist.append(day)
        self.stats_today = {}
        for machine in self.machines:
            machine.end_of_day()
        # Was today a hungry day? (Unmet need for several ticks.)
        total_unful = sum(self.unfulfilled.values())
        if total_unful - self._unfulfilled_seen >= config.HUNGRY_DAY_TICKS:
            self.hungry_days += 1
        else:
            self.hungry_days = max(0, self.hungry_days - 1)
        self._unfulfilled_seen = total_unful

    def yesterday_profit(self) -> int:
        """Coin made minus coin spent across all products, yesterday."""
        total = 0
        for hist in self.stats_history.values():
            if hist:
                total += hist[-1].profit
        return total

    def net_worth(self) -> int:
        """Cents: coin plus book value of land, buildings, vehicles, stock."""
        worth = self.money + len(self.plots) * config.PARCEL_PRICE
        for m in self.machines:
            worth += cents(m.definition.build_cost) * m.level
        for v in self.vehicles:
            worth += cents(v.definition.buy_cost)
        for plot in self.plots:
            for pid, qty in plot.inventory.items():
                if qty > 0:
                    worth += cents(PRODUCTS.get(pid).base_price) * qty
        return worth

    # --- selling -----------------------------------------------------------
    def produced_products(self) -> Set[str]:
        out: Set[str] = set()
        for m in self.machines:
            out.update(m.definition.outputs.keys())
        return out

    def sellable_products(self) -> Set[str]:
        """Products on offer: own machine outputs, plus anything stocked on
        a parcel with a reseller building (store/warehouse)."""
        out = self.produced_products()
        for plot in self.plots:
            if plot.resells():
                out.update(pid for pid, q in plot.inventory.items() if q > 0)
        return out

    def selling_plots(self, product_id: str) -> List["Plot"]:
        """Parcels whose stock of product_id is actually for sale."""
        produced = product_id in self.produced_products()
        return [p for p in self.plots
                if p.inventory.get(product_id, 0) > 0
                and (produced or p.resells())]

    def sells(self, product_id: str) -> bool:
        """True if this person offers product_id for sale right now."""
        return bool(self.selling_plots(product_id))

    def price_of(self, product_id: str) -> int:
        if product_id not in self.prices:
            self.prices[product_id] = cents(PRODUCTS.get(product_id).base_price)
        return self.prices[product_id]

    def adjust_prices_daily(self, world=None) -> None:
        """Supply-demand price discovery from what this seller observed
        today, at cent granularity but in meaningful moves: sold out ->
        raise ~10%; nothing sold (with stock) -> undercut the cheapest
        competitor they know of, or cut ~7% if they know of none cheaper;
        selling steadily with stock left -> hold. Player prices are manual."""
        if self.is_player:
            return
        for pid in self.sellable_products():
            price = self.price_of(pid)
            floor = min_sale_price(pid)
            sold = self.stat(pid).sold
            stock = self.stock(pid)
            if sold > 0 and stock == 0:
                price = max(int(price * config.PRICE_UP_FACTOR), price + 5)
            elif sold == 0 and stock > 0:
                comp = self._cheapest_competitor(world, pid)
                if comp is not None and comp <= price:
                    undercut = max(1, int(comp * config.UNDERCUT_FRAC))
                    price = comp - undercut
                else:
                    price = int(price * config.PRICE_DOWN_FACTOR)
            self.prices[pid] = max(floor, price)

    def _cheapest_competitor(self, world, product_id: str) -> Optional[int]:
        """Lowest sticker price among people *this seller knows* who are
        offering the product right now."""
        if world is None:
            return None
        best = None
        for sid in self.knowledge:
            other = world.people.get(sid)
            if other is None or not other.sells(product_id):
                continue
            p = other.price_of(product_id)
            if best is None or p < best:
                best = p
        return best

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Person {self.id} {self.name} ${self.money}>"
