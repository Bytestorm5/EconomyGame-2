"""People: inventory, money, hunger, knowledge, and what they sell."""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Set

import math
from functools import lru_cache

from ..content.machines import MACHINES
from ..content.products import PRODUCTS
from . import config
from .machine import Machine


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


class Person:
    def __init__(self, pid: int, name: str, money: int, is_player: bool = False):
        self.id = pid
        self.name = name
        self.money = money
        self.is_player = is_player

        self.inventory: Counter = Counter()
        self.hunger = 0
        self.missed_meals = 0  # ticks spent above threshold without food

        # Knowledge graph: ids of people this person knows.
        self.knowledge: Set[int] = set()

        # Sale prices per product id. Only products this person actually
        # produces (machine outputs) are offered for sale.
        self.prices: Dict[str, int] = {}
        # Daily bookkeeping for NPC price adjustment.
        self.sales_today: Counter = Counter()

        self.plot_id: Optional[int] = None
        self.machines: List[Machine] = []  # mirrors the plot's filled slots

    # --- inventory helpers -------------------------------------------------
    def add_items(self, product_id: str, qty: int) -> None:
        self.inventory[product_id] += qty

    def remove_items(self, product_id: str, qty: int) -> None:
        have = self.inventory.get(product_id, 0)
        if have < qty:
            raise ValueError(f"{self.name} lacks {qty} {product_id} (has {have})")
        self.inventory[product_id] = have - qty

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
            and self.inventory.get(product_id, 0) > 0
        )

    def price_of(self, product_id: str) -> int:
        if product_id not in self.prices:
            self.prices[product_id] = PRODUCTS.get(product_id).base_price
        return self.prices[product_id]

    def adjust_prices_daily(self) -> None:
        """NPC rule-of-thumb pricing. The player sets prices manually."""
        if self.is_player:
            self.sales_today.clear()
            return
        for pid in self.produced_products():
            price = self.price_of(pid)
            stock = self.inventory.get(pid, 0)
            if stock == 0 and self.sales_today.get(pid, 0) > 0:
                price = max(int(price * config.PRICE_UP_FACTOR), price + 1)
            elif stock > config.STOCKPILE_THRESHOLD:
                price = max(min_sale_price(pid),
                            int(price * config.PRICE_DOWN_FACTOR))
            self.prices[pid] = price
        self.sales_today.clear()

    # --- needs -------------------------------------------------------------
    def eat_from_inventory(self) -> bool:
        """Eat the best food on hand. Returns True if something was eaten."""
        for pid in config.FOOD_PREFERENCE:
            if self.inventory.get(pid, 0) > 0:
                self.remove_items(pid, 1)
                food = PRODUCTS.get(pid)
                self.hunger = max(
                    0, self.hunger - food.food_value * config.HUNGER_PER_FOOD_VALUE)
                return True
        return False

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Person {self.id} {self.name} ${self.money}>"
